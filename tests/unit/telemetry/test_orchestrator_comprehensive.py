# SPDX-License-Identifier: Apache-2.0
"""Comprehensive tests for the async telemetry orchestrator."""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Base, Run, Target, Task, TelemetrySample
from signal_bench.telemetry import OrchestratorConfig, TelemetryOrchestrator
from signal_bench.telemetry.exceptions import (
    OrchestratorError,
    SourceDataError,
    SourceStartError,
    TelemetryError,
)
from tests.unit.telemetry._programmable_source import (
    ProgrammableMockConfig,
    ProgrammableMockSource,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.asyncio


@pytest.fixture
def orchestrator_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'orchestrator-comprehensive.db'}")

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
        return run.telemetry_partial, list(run.telemetry_partial_sources or [])


def _row_count(session_factory: sessionmaker[Session], run_id: str) -> int:
    with session_factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(TelemetrySample)
            .where(TelemetrySample.run_id == run_id)
        )
        assert count is not None
        return count


async def test_stop_before_start_is_idempotent(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    first = await orchestrator.stop_run()
    second = await orchestrator.stop_run()

    assert first.samples_written == 0
    assert second.samples_written == 0


async def test_start_requires_at_least_one_source(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    with pytest.raises(SourceStartError):
        await orchestrator.start_run(run_id, [])


async def test_start_while_running_raises(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)
    await orchestrator.start_run(run_id, [ProgrammableMockSource()])

    with pytest.raises(OrchestratorError):
        await orchestrator.start_run(run_id, [ProgrammableMockSource()])

    await orchestrator.stop_run()


async def test_one_source_disconnect_marks_partial_and_others_continue(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    failing = ProgrammableMockSource(
        ProgrammableMockConfig(name="disconnecting", fail_after_n_samples=2),
    )
    healthy = ProgrammableMockSource(ProgrammableMockConfig(name="healthy", sample_rate_hz=30.0))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [failing, healthy])
    await asyncio.sleep(0.25)
    state = await orchestrator.stop_run()

    assert state.partial is True
    assert state.failed_sources == ["disconnecting"]
    assert state.samples_per_source["healthy"] > 2
    assert _run_partial(orchestrator_session_factory, run_id) == (True, ["disconnecting"])


async def test_all_sources_disconnect_marks_partial_without_crashing(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    sources = [
        ProgrammableMockSource(ProgrammableMockConfig(name="left", fail_after_n_samples=1)),
        ProgrammableMockSource(ProgrammableMockConfig(name="right", fail_after_n_samples=1)),
    ]
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, sources)
    await asyncio.sleep(0.15)
    state = await orchestrator.stop_run()

    assert state.partial is True
    assert state.failed_sources == ["left", "right"]
    assert _run_partial(orchestrator_session_factory, run_id) == (True, ["left", "right"])


async def test_source_start_failure_marks_partial_without_db_rows(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="bad", fail_on_start=True))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [source])
    state = await orchestrator.stop_run()

    assert state.partial is True
    assert state.failed_sources == ["bad"]
    assert _row_count(orchestrator_session_factory, run_id) == 0
    assert _run_partial(orchestrator_session_factory, run_id) == (True, ["bad"])


async def test_partial_start_failure_keeps_started_sources_running(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    started = ProgrammableMockSource(ProgrammableMockConfig(name="started"))
    failed = ProgrammableMockSource(ProgrammableMockConfig(name="failed", fail_on_start=True))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [started, failed])
    await asyncio.sleep(0.1)
    state = await orchestrator.stop_run()

    assert state.partial is True
    assert state.failed_sources == ["failed"]
    assert started.stop_calls >= 1
    assert started.stopped is True
    assert _row_count(orchestrator_session_factory, run_id) > 0


@pytest.mark.parametrize("exception_type", [SourceDataError, TelemetryError, RuntimeError])
async def test_source_failure_types_mark_partial(
    orchestrator_session_factory: sessionmaker[Session],
    exception_type: type[Exception],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    failing = ProgrammableMockSource(
        ProgrammableMockConfig(
            name="flaky",
            fail_after_n_samples=1,
            failure_exception=exception_type,
        ),
    )
    healthy = ProgrammableMockSource(ProgrammableMockConfig(name="healthy", sample_rate_hz=25.0))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [failing, healthy])
    await asyncio.sleep(0.2)
    state = await orchestrator.stop_run()

    assert state.partial is True
    assert state.failed_sources == ["flaky"]
    assert _run_partial(orchestrator_session_factory, run_id) == (True, ["flaky"])


async def test_finite_source_ending_unexpectedly_marks_partial(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    finite = ProgrammableMockSource(ProgrammableMockConfig(name="finite", samples_to_emit=1))
    healthy = ProgrammableMockSource(ProgrammableMockConfig(name="healthy"))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [finite, healthy])
    await asyncio.sleep(0.15)
    state = await orchestrator.stop_run()

    assert state.failed_sources == ["finite"]
    assert _run_partial(orchestrator_session_factory, run_id) == (True, ["finite"])


async def test_stop_twice_after_run_is_idempotent(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)
    await orchestrator.start_run(run_id, [ProgrammableMockSource()])
    await asyncio.sleep(0.08)

    first = await orchestrator.stop_run()
    second = await orchestrator.stop_run()

    assert first.samples_written > 0
    assert second.samples_written == first.samples_written


async def test_grouped_samples_fan_out_to_scalar_rows(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(
        ProgrammableMockConfig(
            name="grouped",
            sample_values={"voltage": 3.3, "current": 0.2, "power": 0.66},
        ),
    )
    orchestrator = TelemetryOrchestrator(
        orchestrator_session_factory,
        OrchestratorConfig(batch_size=2, flush_interval_s=0.01),
    )

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.25)
    state = await orchestrator.stop_run()

    assert state.samples_written >= 3
    assert state.rows_written == state.samples_written * 3
    with orchestrator_session_factory() as session:
        metrics = session.scalars(
            select(TelemetrySample.metric)
            .where(TelemetrySample.run_id == run_id)
            .order_by(TelemetrySample.metric),
        ).all()
    assert metrics.count("voltage") == state.samples_written
    assert metrics.count("current") == state.samples_written
    assert metrics.count("power") == state.samples_written


async def test_queue_backpressure_bounds_fast_source_when_writer_is_slow(
    orchestrator_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(
        ProgrammableMockConfig(name="fast", sample_rate_hz=500.0),
    )
    orchestrator = TelemetryOrchestrator(
        orchestrator_session_factory,
        OrchestratorConfig(queue_maxsize=1, batch_size=1, flush_interval_s=0.001),
    )
    original_insert = orchestrator._insert_rows

    def _slow_insert(rows: list[dict[str, object]]) -> None:
        time.sleep(0.01)
        original_insert(rows)

    monkeypatch.setattr(orchestrator, "_insert_rows", _slow_insert)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.12)
    state = await orchestrator.stop_run()

    assert 1 <= state.samples_written <= 40
    assert state.rows_written == state.samples_written * 3


async def test_stop_source_timeout_is_nonfatal(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(
        ProgrammableMockConfig(name="slow-stop", stop_delay_s=0.2),
    )
    orchestrator = TelemetryOrchestrator(
        orchestrator_session_factory,
        OrchestratorConfig(shutdown_timeout_s=0.01, flush_interval_s=0.01),
    )

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.05)
    state = await orchestrator.stop_run()

    assert state.samples_written >= 1


async def test_stop_source_exception_is_nonfatal(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    source = ProgrammableMockSource(ProgrammableMockConfig(name="bad-stop", stop_raises=True))
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [source])
    await asyncio.sleep(0.05)
    state = await orchestrator.stop_run()

    assert state.samples_written >= 1
