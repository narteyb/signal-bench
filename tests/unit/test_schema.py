# SPDX-License-Identifier: Apache-2.0
from datetime import datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signal_bench import __version__
from signal_bench.schema import Run, Target, Task


def test_create_target_minimal(session: Session) -> None:
    target = Target(name="esp32-s3-devkitc-1", kind="mcu")
    session.add(target)
    session.commit()

    fetched = session.get(Target, target.target_id)
    assert fetched is not None
    assert fetched.name == "esp32-s3-devkitc-1"
    assert fetched.kind == "mcu"


def test_create_run_with_fk(session: Session) -> None:
    target = Target(name="local-dev", kind="local")
    task = Task(name="tinyml-wake-word-v1", version="1.0.0")
    session.add_all([target, task])
    session.flush()

    run = Run(
        target_id=target.target_id,
        task_id=task.task_id,
        started_at=datetime(2026, 5, 2, 12, 0, 0),
        status="running",
        corpus_tag="X",
        warmup_count=1,
        measurement_count=3,
        signal_bench_version=__version__,
    )
    session.add(run)
    session.commit()

    fetched = session.get(Run, run.run_id)
    assert fetched is not None
    assert fetched.target.target_id == target.target_id
    assert fetched.task.task_id == task.task_id
    assert fetched.telemetry_partial is False
    assert fetched.telemetry_partial_sources is None
    assert fetched.partial_reasons is None


def test_run_without_target_fails(session: Session) -> None:
    task = Task(name="tinyml-wake-word-v1", version="1.0.0")
    session.add(task)
    session.flush()

    session.add(
        Run(
            target_id="missing",
            task_id=task.task_id,
            started_at=datetime(2026, 5, 2, 12, 0, 0),
            status="running",
            corpus_tag="X",
            warmup_count=1,
            measurement_count=3,
            signal_bench_version=__version__,
        ),
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_status_field_accepts_valid_values(session: Session) -> None:
    target = Target(name="local-dev", kind="local")
    task = Task(name="tinyml-wake-word-v1", version="1.0.0")
    session.add_all([target, task])
    session.flush()

    for index, status in enumerate(["running", "completed", "failed", "aborted"], start=1):
        session.add(
            Run(
                target_id=target.target_id,
                task_id=task.task_id,
                started_at=datetime(2026, 5, 2, 12, index, 0),
                status=status,
                corpus_tag="X",
                warmup_count=1,
                measurement_count=3,
                signal_bench_version=__version__,
            ),
        )

    session.commit()
    assert session.query(Run).count() == 4


def test_telemetry_sample_indexed(session: Session) -> None:
    indexes = inspect(session.bind).get_indexes("telemetry_samples")
    indexed_columns = {tuple(index["column_names"]) for index in indexes}
    assert ("run_id", "timestamp") in indexed_columns


def test_unique_target_name_kind(session: Session) -> None:
    session.add_all(
        [
            Target(name="esp32-s3-devkitc-1", kind="mcu"),
            Target(name="esp32-s3-devkitc-1", kind="mcu"),
        ],
    )

    with pytest.raises(IntegrityError):
        session.commit()
