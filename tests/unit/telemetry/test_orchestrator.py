# SPDX-License-Identifier: Apache-2.0
import asyncio
import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Base, Run, Target, Task, TelemetrySample
from signal_bench.telemetry import MockTelemetrySource, TelemetryOrchestrator

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]


@pytest.fixture
def orchestrator_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'orchestrator.db'}")

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


async def test_orchestrator_smoke_writes_mock_samples(
    orchestrator_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(orchestrator_session_factory)
    orchestrator = TelemetryOrchestrator(orchestrator_session_factory)

    await orchestrator.start_run(run_id, [MockTelemetrySource(rate_hz=10.0)])
    await asyncio.sleep(2.05)
    state = await orchestrator.stop_run()

    assert state.partial is False
    assert state.failed_sources == []
    assert state.samples_written >= 10
    assert state.rows_written >= 10
    with orchestrator_session_factory() as session:
        sample_count = session.scalar(
            select(func.count())
            .select_from(TelemetrySample)
            .where(TelemetrySample.run_id == run_id),
        )
        run = session.get(Run, run_id)

    assert sample_count == state.rows_written
    assert run is not None
    assert run.telemetry_partial is False
    assert run.telemetry_partial_sources is None
