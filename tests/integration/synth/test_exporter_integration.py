# SPDX-License-Identifier: Apache-2.0
"""Integration tests for SQLite-to-YAML matrix export."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench.schema import Base, Result, Run, Target, Task, TelemetrySample
from signal_bench.synth.exporter import export_matrix
from signal_bench.synth.matrix_config import MatrixConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import Engine

START = dt.datetime(2026, 5, 15, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def sqlite_session(tmp_path: Path) -> Iterator[Session]:
    engine: Engine = create_engine(f"sqlite:///{tmp_path / 'exporter.db'}")
    Base.metadata.create_all(engine)
    try:
        maker = sessionmaker(bind=engine)
        with maker() as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _config() -> MatrixConfig:
    return MatrixConfig.model_validate(
        {
            "schema_version": 1,
            "name": "post-1-test",
            "version": "1.0.0",
            "description": "Integration test matrix.",
            "created": "2026-05-15",
            "tasks": ["kws"],
            "targets": ["f401re"],
            "defaults": {
                "iterations": 100,
                "warmup_iterations": 10,
                "latency_budget_ms": None,
                "accuracy_threshold": 0.8,
                "energy_budget_uwh": None,
            },
            "cells": [{"task": "kws", "target": "f401re"}],
            "exclusions": [],
        },
    )


def _seed_run(
    session: Session,
    *,
    run_id: str,
    started_at: dt.datetime,
    telemetry_partial: bool = False,
) -> None:
    target = session.get(Target, "target-f401re")
    if target is None:
        target = Target(target_id="target-f401re", name="f401re", kind="mcu")
        session.add(target)
    task = session.get(Task, "task-kws")
    if task is None:
        task = Task(task_id="task-kws", name="kws", version="mlperf-tiny-v1.3")
        session.add(task)
    session.flush()

    run = Run(
        run_id=run_id,
        target_id=target.target_id,
        task_id=task.task_id,
        started_at=started_at,
        finished_at=started_at + dt.timedelta(seconds=30),
        status="completed",
        corpus_tag="X",
        warmup_count=0,
        measurement_count=10,
        signal_bench_version="test",
        model_name="kws",
        model_hash="hash-kws",
        quantization="int8",
        telemetry_partial=telemetry_partial,
        telemetry_partial_sources=["fnb58"] if telemetry_partial else None,
    )
    session.add(run)
    session.flush()

    for sequence in range(10):
        session.add(
            Result(
                result_id=f"{run_id}-result-{sequence}",
                run_id=run_id,
                sequence=sequence,
                started_at=started_at + dt.timedelta(milliseconds=sequence),
                duration_ms=1.0 + sequence / 100,
            ),
        )
    for offset_s in (0.0, 10.0, 20.0, 30.0):
        session.add(
            TelemetrySample(
                run_id=run_id,
                timestamp=started_at + dt.timedelta(seconds=offset_s),
                source="fnb58",
                metric="power",
                value=5.0,
            ),
        )
    session.commit()


def test_exporter_writes_matrix_yaml(sqlite_session: Session, tmp_path: Path) -> None:
    _seed_run(sqlite_session, run_id="run-1", started_at=START)
    output_path = tmp_path / "post-1-data.yml"

    data = export_matrix(_config(), sqlite_session, output_path)
    payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))

    assert data.generated_from_runs == 1
    assert payload["schema_version"] == 1
    assert payload["cells"][0]["runs"][0]["latency_stats"]["n_samples"] == 10
    assert payload["cells"][0]["runs"][0]["energy_stats"]["avg_power_w"] == pytest.approx(5.0)


def test_exporter_keeps_multiple_runs(sqlite_session: Session) -> None:
    _seed_run(sqlite_session, run_id="run-1", started_at=START)
    _seed_run(sqlite_session, run_id="run-2", started_at=START + dt.timedelta(minutes=1))

    payload = export_matrix(_config(), sqlite_session, output_path=None).to_dict()

    assert [run["run_id"] for run in payload["cells"][0]["runs"]] == ["run-1", "run-2"]


def test_exporter_preserves_partial_telemetry_flag(sqlite_session: Session) -> None:
    _seed_run(sqlite_session, run_id="run-1", started_at=START, telemetry_partial=True)

    run = export_matrix(_config(), sqlite_session, output_path=None).to_dict()["cells"][0]["runs"][
        0
    ]

    assert run["telemetry_partial"] is True
    assert run["telemetry_partial_sources"] == ["fnb58"]
