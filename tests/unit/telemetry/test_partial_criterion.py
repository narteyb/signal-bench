# SPDX-License-Identifier: Apache-2.0
import asyncio
import datetime as dt
import logging
import time
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
from signal_bench.telemetry.exceptions import OrchestratorError
from signal_bench.telemetry.orchestrator import (
    PARTIAL_COVERAGE_THRESHOLD_ENV,
    get_partial_coverage_threshold,
)
from tests.unit.telemetry._programmable_source import (
    ProgrammableMockConfig,
    ProgrammableMockSource,
)


@pytest.fixture
def orchestrator_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'partial-criterion.db'}")

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


def _run_partial(session_factory: sessionmaker[Session], run_id: str) -> tuple[bool, list[str]]:
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run.telemetry_partial, list(run.partial_reasons or [])


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


def _sample(*, source: str) -> TelemetrySample:
    return TelemetrySample(
        timestamp=dt.datetime.now(dt.UTC),
        source_name=source,
        values={"power": 1.0},
    )


def _decision_orchestrator(
    session_factory: sessionmaker[Session],
    *,
    sources: list[ProgrammableMockSource],
    duration_s: float,
    sample_counts: dict[str, int],
) -> TelemetryOrchestrator:
    orchestrator = TelemetryOrchestrator(session_factory)
    orchestrator._sources = sources
    orchestrator._run_started_monotonic = time.monotonic() - duration_s
    orchestrator._state.samples_per_source.update(sample_counts)
    return orchestrator


def test_all_sources_fully_covered_is_not_partial(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    source = ProgrammableMockSource(ProgrammableMockConfig(name="full", sample_rate_hz=10.0))
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=10.0,
        sample_counts={"full": 100},
    )

    decision = orchestrator._decide_telemetry_partial()

    assert decision.partial is False
    assert decision.reasons == []
    assert decision.per_source_coverage == {"full": 1.0}


@pytest.mark.asyncio
async def test_source_start_failure_sets_partial_with_reason(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="bad", fail_on_start=True))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [source])
    await orchestrator.stop_run()

    partial, reasons = _run_partial(orchestrator_session_factory, run_id)
    assert partial is True
    assert reasons == ["bad: coverage=0%, threshold=90%, samples=0/1"]


def test_disconnect_with_less_than_ten_percent_loss_is_not_partial(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    source = ProgrammableMockSource(ProgrammableMockConfig(name="brief-drop", sample_rate_hz=10.0))
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=10.0,
        sample_counts={"brief-drop": 95},
    )

    decision = orchestrator._decide_telemetry_partial()

    assert decision.partial is False
    assert decision.sources == []


def test_small_short_run_sample_deficit_is_not_partial(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    source = ProgrammableMockSource(ProgrammableMockConfig(name="short", sample_rate_hz=50.0))
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=1.0,
        sample_counts={"short": 44},
    )

    decision = orchestrator._decide_telemetry_partial()

    assert decision.partial is False
    assert decision.per_source_coverage == {"short": 0.88}


def test_disconnect_with_more_than_ten_percent_loss_is_partial(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    source = ProgrammableMockSource(ProgrammableMockConfig(name="long-drop", sample_rate_hz=10.0))
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=10.0,
        sample_counts={"long-drop": 72},
    )

    decision = orchestrator._decide_telemetry_partial()

    assert decision.partial is True
    assert decision.sources == ["long-drop"]
    assert decision.reasons == ["long-drop: coverage=72%, threshold=90%, samples=72/100"]


def test_slow_source_throughout_is_partial(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    source = ProgrammableMockSource(ProgrammableMockConfig(name="slow", sample_rate_hz=10.0))
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=10.0,
        sample_counts={"slow": 60},
    )

    decision = orchestrator._decide_telemetry_partial()

    assert decision.partial is True
    assert decision.reasons == ["slow: coverage=60%, threshold=90%, samples=60/100"]


@pytest.mark.asyncio
async def test_db_write_failure_is_partial_with_db_writer_reason(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="writer", sample_rate_hz=20.0))
    orchestrator = TelemetryOrchestrator(
        orchestrator_session_factory,
        OrchestratorConfig(batch_size=1, flush_interval_s=0.001),
    )

    def _raise_insert(_rows: list[dict[str, object]]) -> None:
        msg = "disk full"
        raise RuntimeError(msg)

    monkeypatch.setattr(orchestrator, "_insert_rows", _raise_insert)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.05)
    with pytest.raises(OrchestratorError):
        await orchestrator.stop_run()

    partial, reasons = _run_partial(orchestrator_session_factory, run_id)
    assert partial is True
    assert any(reason.startswith("db_writer: write failed") for reason in reasons)
    assert _event(caplog, "telemetry_partial_decided").context["partial"] is True


@pytest.mark.asyncio
async def test_db_write_lagging_without_loss_is_not_partial(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="laggy", sample_rate_hz=10.0))
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=10.0,
        sample_counts={"laggy": 100},
    )
    orchestrator._run_id = "run-lag"
    orchestrator._queue = asyncio.Queue(maxsize=1)
    orchestrator._queue.put_nowait(
        _sample(source="laggy"),
    )
    orchestrator._maybe_log_write_lag()

    assert _event(caplog, "db_write_lagging").context["queue_fraction"] >= 0.8
    decision = orchestrator._decide_telemetry_partial()
    assert decision.partial is False
    assert decision.reasons == []


def test_threshold_env_override_makes_sixty_percent_coverage_non_partial(
    orchestrator_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PARTIAL_COVERAGE_THRESHOLD_ENV, "0.50")
    source = ProgrammableMockSource(ProgrammableMockConfig(name="loose", sample_rate_hz=10.0))
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=10.0,
        sample_counts={"loose": 60},
    )

    decision = orchestrator._decide_telemetry_partial()

    assert get_partial_coverage_threshold() == 0.5
    assert decision.partial is False


@pytest.mark.parametrize("value", ["0", "1.5", "not-a-float"])
def test_invalid_threshold_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(PARTIAL_COVERAGE_THRESHOLD_ENV, value)

    with pytest.raises(ValueError, match=PARTIAL_COVERAGE_THRESHOLD_ENV):
        get_partial_coverage_threshold()


def test_per_source_threshold_override_wins_over_global_default(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    source = ProgrammableMockSource(ProgrammableMockConfig(name="override", sample_rate_hz=10.0))
    source.partial_coverage_threshold = 0.5
    orchestrator = _decision_orchestrator(
        orchestrator_session_factory,
        sources=[source],
        duration_s=10.0,
        sample_counts={"override": 60},
    )

    decision = orchestrator._decide_telemetry_partial()

    assert decision.partial is False
    assert decision.per_source_coverage == {"override": 0.6}


@pytest.mark.asyncio
async def test_telemetry_partial_decided_event_schema_for_clean_run(
    orchestrator_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_caplog(caplog)
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="healthy", sample_rate_hz=20.0))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.12)
    await orchestrator.stop_run()

    event_record = _event(caplog, "telemetry_partial_decided")
    assert event_record.run_id == run_id
    assert event_record.context["partial"] is False
    assert event_record.context["criterion"] == "coverage_below_threshold"
    assert event_record.context["threshold_frac"] == 0.9
    assert event_record.context["reasons"] == []
