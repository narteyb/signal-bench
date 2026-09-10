# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures for telemetry integration tests."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Base, Result, Run, Target, Task, TelemetrySample

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session


@pytest.fixture
def telemetry_db_path(tmp_path: Path) -> Path:
    return tmp_path / "telemetry-integration.db"


@pytest.fixture
def telemetry_engine(telemetry_db_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{telemetry_db_path}")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, _connection_record: object) -> None:
        assert hasattr(dbapi_connection, "cursor")
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
def telemetry_session_factory(telemetry_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=telemetry_engine)


def create_run(session_factory: sessionmaker[Session], *, started_at: dt.datetime) -> str:
    """Create one benchmark run row for in-process orchestrator tests."""
    with session_factory() as session:
        target = Target(name=f"target-{new_id()}", kind="telemetry-integration")
        task = Task(name=f"task-{new_id()}", version="test")
        session.add_all([target, task])
        session.flush()
        run = Run(
            target_id=target.target_id,
            task_id=task.task_id,
            started_at=started_at,
            status="running",
            corpus_tag="X",
            warmup_count=0,
            measurement_count=0,
            signal_bench_version=__version__,
        )
        session.add(run)
        session.commit()
        return run.run_id


def finish_run(session_factory: sessionmaker[Session], run_id: str) -> None:
    """Mark a synthetic run completed for timing helpers that inspect run bounds."""
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        run.status = "completed"
        run.finished_at = dt.datetime.now(dt.UTC)
        session.commit()


def latest_run(session_factory: sessionmaker[Session]) -> Run:
    """Return the most recent run from a test database."""
    with session_factory() as session:
        run = session.query(Run).order_by(Run.started_at.desc()).first()
        assert run is not None
        session.expunge(run)
        return run


def add_result_grid(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
    count: int,
    interval_s: float,
    duration_ms: float,
) -> None:
    """Add evenly-spaced inference windows over a run."""
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        for sequence in range(count):
            session.add(
                Result(
                    run_id=run_id,
                    sequence=sequence,
                    started_at=run.started_at + dt.timedelta(seconds=sequence * interval_s),
                    duration_ms=duration_ms,
                ),
            )
        run.measurement_count = count
        session.commit()


def add_synthetic_telemetry(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
    source: str,
    offsets_s: list[float],
    metric: str = "power",
) -> None:
    """Insert scalar telemetry rows for one source metric."""
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        for offset_s in offsets_s:
            session.add(
                TelemetrySample(
                    run_id=run_id,
                    timestamp=run.started_at + dt.timedelta(seconds=offset_s),
                    source=source,
                    metric=metric,
                    value=1.0,
                ),
            )
        session.commit()
