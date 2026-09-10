# SPDX-License-Identifier: Apache-2.0
import asyncio
import datetime as dt
import logging
import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Base, Run, Target, Task
from signal_bench.telemetry import OrchestratorConfig, TelemetryOrchestrator
from signal_bench.telemetry.base import TelemetrySample
from signal_bench.telemetry.exceptions import OrchestratorError, SourceDataError, TelemetryError
from signal_bench.telemetry.orchestrator import (
    CLOCK_SKEW_THRESHOLD_S,
    RATE_LOW_DURATION_S,
)
from signal_bench.telemetry.sources.fnirsi import FnirsiSource, FnirsiSourceConfig
from tests.unit.telemetry._programmable_source import (
    ProgrammableMockConfig,
    ProgrammableMockSource,
)


@pytest.fixture
def orchestrator_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'orchestrator-logging.db'}")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def orchestrator_session_factory(orchestrator_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=orchestrator_engine)


def _create_run(session_factory: sessionmaker[Session]) -> str:
    with session_factory() as session:
        target = Target(name=f"target-{new_id()}", kind="telemetry-test")
        task = Task(name=f"task-{new_id()}", version="0")
        session.add_all([target, task])
        session.flush()
        run = Run(
            target_id=target.target_id,
            task_id=task.task_id,
            started_at=dt.datetime.now(dt.UTC),
            status="running",
            corpus_tag="X",
            warmup_count=0,
            measurement_count=0,
            signal_bench_version=__version__,
        )
        session.add(run)
        session.commit()
        return run.run_id


def _events(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if hasattr(record, "event")]


def _event(caplog: pytest.LogCaptureFixture, name: str) -> logging.LogRecord:
    for record in _events(caplog):
        if record.event == name:
            return record
    event_names = [record.event for record in _events(caplog)]
    pytest.fail(f"missing event {name}; saw {event_names}")


def _configure_caplog(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="signal_bench.telemetry")


@pytest.mark.asyncio
async def test_lifecycle_events_include_run_and_source_context(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="healthy"))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.08)
    await orchestrator.stop_run()

    assert _event(caplog, "run_started").run_id == run_id
    source_started = _event(caplog, "source_started")
    assert source_started.source == "healthy"
    assert source_started.context["sample_rate_hz"] == source.sample_rate_hz
    run_completed = _event(caplog, "run_completed")
    assert run_completed.context["partial"] is False
    assert run_completed.context["samples_written"] > 0


@pytest.mark.asyncio
async def test_source_start_failure_is_structured(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="bad", fail_on_start=True))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [source])
    await orchestrator.stop_run()

    event_record = _event(caplog, "source_start_failed")
    assert event_record.source == "bad"
    assert event_record.run_id == run_id
    assert event_record.context["error_class"] == "SourceStartError"


@pytest.mark.parametrize(
    ("exception_type", "expected_event"),
    [
        (SourceDataError, "source_data_error"),
        (TelemetryError, "source_telemetry_error"),
        (RuntimeError, "source_unhandled_exception"),
    ],
)
@pytest.mark.asyncio
async def test_source_failure_events_are_structured(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    exception_type: type[Exception],
    expected_event: str,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    failing = ProgrammableMockSource(
        ProgrammableMockConfig(
            name="flaky",
            fail_after_n_samples=1,
            failure_exception=exception_type,
        ),
    )
    healthy = ProgrammableMockSource(ProgrammableMockConfig(name="healthy", sample_rate_hz=30.0))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [failing, healthy])
    await asyncio.sleep(0.2)
    await orchestrator.stop_run()

    event_record = _event(caplog, expected_event)
    assert event_record.source == "flaky"
    assert event_record.context["error_class"] == exception_type.__name__
    partial = _event(caplog, "partial_data_threshold_crossed")
    assert partial.context["failed_sources"] == ["flaky"]


@pytest.mark.asyncio
async def test_source_disconnect_event_is_structured(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    failing = ProgrammableMockSource(
        ProgrammableMockConfig(name="disconnecting", fail_after_n_samples=1),
    )
    healthy = ProgrammableMockSource(ProgrammableMockConfig(name="healthy"))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [failing, healthy])
    await asyncio.sleep(0.2)
    await orchestrator.stop_run()

    event_record = _event(caplog, "source_disconnected")
    assert event_record.source == "disconnecting"
    assert event_record.context["error_class"] == "SourceDisconnectError"


@pytest.mark.asyncio
async def test_unexpected_finite_source_stop_logs_warning(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    finite = ProgrammableMockSource(ProgrammableMockConfig(name="finite", samples_to_emit=1))
    healthy = ProgrammableMockSource(ProgrammableMockConfig(name="healthy"))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [finite, healthy])
    await asyncio.sleep(0.15)
    await orchestrator.stop_run()

    assert _event(caplog, "source_stopped_unexpectedly").source == "finite"


@pytest.mark.asyncio
async def test_teardown_failure_logs_structured_event(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="bad-stop", stop_raises=True))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.05)
    await orchestrator.stop_run()

    event_record = _event(caplog, "orchestrator_teardown_failed")
    assert event_record.source == "bad-stop"
    assert event_record.context["reason"] == "source_stop_failed"


@pytest.mark.asyncio
async def test_db_write_lagging_event_fires_when_queue_is_nearly_full(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="fast", sample_rate_hz=300.0))
    orchestrator = TelemetryOrchestrator(
        orchestrator_session_factory,
        OrchestratorConfig(queue_maxsize=1, batch_size=1, flush_interval_s=0.001),
    )
    original_insert = orchestrator._insert_rows

    def _slow_insert(rows: list[dict[str, object]]) -> None:
        time.sleep(0.02)
        original_insert(rows)

    monkeypatch.setattr(orchestrator, "_insert_rows", _slow_insert)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.08)
    await orchestrator.stop_run()

    event_record = _event(caplog, "db_write_lagging")
    assert event_record.context["queue_fraction"] >= 0.8


@pytest.mark.asyncio
async def test_db_write_failure_logs_and_raises_orchestrator_error(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="writer-failure"))
    orchestrator = TelemetryOrchestrator(
        orchestrator_session_factory,
        OrchestratorConfig(batch_size=1, flush_interval_s=0.001),
    )

    def _raise_insert(_rows: list[dict[str, object]]) -> None:
        msg = "sqlite locked"
        raise RuntimeError(msg)

    monkeypatch.setattr(orchestrator, "_insert_rows", _raise_insert)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.05)
    with pytest.raises(OrchestratorError):
        await orchestrator.stop_run()

    event_record = _event(caplog, "db_write_failed")
    assert event_record.context["error_class"] == "RuntimeError"
    assert event_record.context["message"] == "sqlite locked"
    assert _event(caplog, "run_failed").context["error_class"] == "OrchestratorError"


def test_sample_rate_below_threshold_event_has_expected_context(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="slow-rate", sample_rate_hz=20.0))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)
    now = time.monotonic()
    orchestrator._sources = [source]
    orchestrator._run_id = "run-rate"
    orchestrator._run_started_monotonic = now - 10.0
    orchestrator._sample_windows = {source.name: deque([now - 1.0])}
    orchestrator._last_sample_monotonic = {source.name: now - 1.0}
    orchestrator._rate_low_started_at = {source.name: now - RATE_LOW_DURATION_S - 0.1}

    orchestrator._check_source_rates(now)

    event_record = _event(caplog, "sample_rate_below_threshold")
    assert event_record.source == "slow-rate"
    assert event_record.context["expected_hz"] == 20.0
    assert event_record.context["observed_hz"] < event_record.context["threshold_hz"]


def test_sample_timestamp_and_clock_skew_events_are_structured(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)
    orchestrator._run_id = "run-time"
    stale = TelemetrySample(
        timestamp=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=90),
        source_name="stale",
        values={"power": 1.0},
    )
    current = TelemetrySample(
        timestamp=dt.datetime.now(dt.UTC),
        source_name="current",
        values={"power": 1.0},
    )
    future = TelemetrySample(
        timestamp=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=CLOCK_SKEW_THRESHOLD_S + 20),
        source_name="future",
        values={"power": 1.0},
    )
    naive = TelemetrySample(
        timestamp=dt.datetime.now(),  # noqa: DTZ005 - deliberately exercises invalid input.
        source_name="naive",
        values={"power": 1.0},
    )

    orchestrator._check_sample_timestamp(stale)
    orchestrator._check_sample_timestamp(current)
    orchestrator._check_sample_timestamp(future)
    orchestrator._check_sample_timestamp(naive)

    assert _event(caplog, "sample_timestamp_stale").source == "stale"
    assert _event(caplog, "clock_skew_detected").context["skew_s"] > CLOCK_SKEW_THRESHOLD_S
    assert _event(caplog, "sample_timestamp_invalid").source == "future"
    invalid_events = [
        record for record in _events(caplog) if record.event == "sample_timestamp_invalid"
    ]
    assert {record.context["reason"] for record in invalid_events} == {
        "future_datetime",
        "naive_datetime",
    }


def test_fnirsi_internal_queue_overflow_logs_drop(caplog: pytest.LogCaptureFixture) -> None:
    _configure_caplog(caplog)
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))
    source._queue = asyncio.Queue(maxsize=1)
    sample = TelemetrySample(
        timestamp=dt.datetime.now(dt.UTC),
        source_name=source.name,
        values={"power": 1.0},
    )
    source._queue.put_nowait(sample)

    source._enqueue_sample(sample)

    event_record = _event(caplog, "queue_overflow_dropping_sample")
    assert event_record.source == "fnb58"
    assert event_record.context["queue_maxsize"] == 256


def test_fnirsi_malformed_notification_logs_debug_before_error_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    source._handle_notification(None, bytearray(b"too-short"))

    event_record = _event(caplog, "source_sample_malformed")
    assert event_record.source == "fnb58"
    assert event_record.context["consecutive_malformed"] == 1
