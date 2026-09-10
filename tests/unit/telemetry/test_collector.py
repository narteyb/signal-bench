# SPDX-License-Identifier: Apache-2.0
import datetime as dt
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Self

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Base, Run, Target, Task, TelemetrySample
from signal_bench.telemetry import MockTelemetrySource, TelemetryCollector


class NamedMockTelemetrySource(MockTelemetrySource):
    """Mock source with an instance-specific source name."""

    def __init__(self: Self, source_name: str, **kwargs: object) -> None:
        """Create a named mock source."""
        super().__init__(**kwargs)
        self.source_name = source_name


@pytest.fixture
def collector_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'collector.db'}")

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
def collector_session_factory(collector_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=collector_engine)


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


def _sample_count(session_factory: sessionmaker[Session], run_id: str) -> int:
    with session_factory() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(TelemetrySample)
                .where(TelemetrySample.run_id == run_id),
            ),
        )


def test_collector_single_source_writes_samples(
    collector_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(collector_session_factory)
    collector = TelemetryCollector([MockTelemetrySource(rate_hz=10.0)], collector_session_factory)

    collector.start(run_id)
    time.sleep(2.05)
    result = collector.stop()

    assert result.partial is False
    assert result.failed_sources == []
    assert result.samples_per_source["mock"] >= 40
    assert _sample_count(collector_session_factory, run_id) == result.samples_written


def test_collector_three_sources_concurrently(
    collector_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(collector_session_factory)
    sources = [
        NamedMockTelemetrySource("mock_a", rate_hz=10.0),
        NamedMockTelemetrySource("mock_b", rate_hz=20.0),
        NamedMockTelemetrySource("mock_c", rate_hz=1.0),
    ]
    collector = TelemetryCollector(sources, collector_session_factory)

    collector.start(run_id)
    time.sleep(2.05)
    result = collector.stop()

    assert result.partial is False
    assert set(result.samples_per_source) == {"mock_a", "mock_b", "mock_c"}
    assert result.samples_per_source["mock_a"] >= 40
    assert result.samples_per_source["mock_b"] >= 80
    assert result.samples_per_source["mock_c"] >= 3


def test_collector_marks_partial_when_source_raises(
    collector_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(collector_session_factory)
    collector = TelemetryCollector(
        [
            MockTelemetrySource(rate_hz=10.0, fail_after=0.5),
            NamedMockTelemetrySource("steady", rate_hz=10.0),
        ],
        collector_session_factory,
    )

    collector.start(run_id)
    time.sleep(2.05)
    result = collector.stop()

    assert result.partial is True
    assert result.failed_sources == ["mock"]
    assert result.samples_per_source["steady"] >= 40
    with collector_session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.telemetry_partial is True
        assert run.telemetry_partial_sources == ["mock"]


def test_collector_stop_leaves_no_telemetry_threads(
    collector_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(collector_session_factory)
    collector = TelemetryCollector([MockTelemetrySource(rate_hz=50.0)], collector_session_factory)

    collector.start(run_id)
    time.sleep(0.25)
    collector.stop()

    names = {thread.name for thread in threading.enumerate()}
    assert not {name for name in names if name.startswith("telemetry-")}


def test_collector_drains_queue_before_returning(
    collector_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_run(collector_session_factory)
    collector = TelemetryCollector([MockTelemetrySource(rate_hz=100.0)], collector_session_factory)

    collector.start(run_id)
    time.sleep(0.35)
    result = collector.stop()

    assert result.samples_written > 0
    assert _sample_count(collector_session_factory, run_id) == result.samples_written
