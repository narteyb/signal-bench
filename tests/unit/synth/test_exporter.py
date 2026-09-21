# SPDX-License-Identifier: Apache-2.0
"""Unit tests for matrix DB export helpers."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from signal_bench.schema import Result, Run, Target, Task, TelemetrySample
from signal_bench.synth.exporter import export_matrix
from signal_bench.synth.matrix_config import MatrixConfig

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

    from signal_bench.synth.matrix_data import MatrixData

START = dt.datetime(2026, 5, 15, 12, 0, tzinfo=dt.UTC)


@dataclass(frozen=True, slots=True)
class SeedRunOptions:
    """Options for seeding one synthetic run row."""

    run_id: str = "run-1"
    task: str = "kws"
    target: str = "f401re"
    started_at: dt.datetime = START
    finished_at: dt.datetime | None = START + dt.timedelta(seconds=30)
    status: str = "completed"
    durations_ms: list[float] | None = None
    warmup_count: int = 0
    power_samples: list[tuple[float, float]] | None = None
    telemetry_partial: bool = False
    telemetry_partial_sources: list[str] | None = None
    power_source: str = "fnb58"
    power_metric: str = "power"
    extra: dict[str, Any] | None = None


def _config(cells: list[dict[str, str]] | None = None) -> MatrixConfig:
    return MatrixConfig.model_validate(
        {
            "schema_version": 1,
            "name": "test-matrix",
            "version": "1.0.0",
            "description": "Test matrix.",
            "created": "2026-05-15",
            "tasks": ["kws", "ic"],
            "targets": ["f401re", "nano33"],
            "defaults": {
                "iterations": 100,
                "warmup_iterations": 10,
                "latency_budget_ms": None,
                "accuracy_threshold": 0.8,
                "energy_budget_uwh": None,
            },
            "cells": cells or [{"task": "kws", "target": "f401re"}],
            "exclusions": [],
            "phase_5_overrides": {},
        },
    )


def _seed_run(session: Session, **overrides: object) -> Run:
    options = SeedRunOptions(**overrides)
    target_row = session.get(Target, f"target-{options.target}")
    if target_row is None:
        target_row = Target(target_id=f"target-{options.target}", name=options.target, kind="test")
        session.add(target_row)
    task_row = session.get(Task, f"task-{options.task}")
    if task_row is None:
        task_row = Task(task_id=f"task-{options.task}", name=options.task, version="test")
        session.add(task_row)
    session.flush()

    durations = options.durations_ms if options.durations_ms is not None else [1.0] * 10
    run = Run(
        run_id=options.run_id,
        target_id=target_row.target_id,
        task_id=task_row.task_id,
        started_at=options.started_at,
        finished_at=options.finished_at,
        status=options.status,
        corpus_tag="X",
        warmup_count=options.warmup_count,
        measurement_count=len(durations),
        signal_bench_version="test",
        model_name=options.task,
        model_hash=f"hash-{options.task}",
        quantization="int8",
        telemetry_partial=options.telemetry_partial,
        telemetry_partial_sources=options.telemetry_partial_sources,
        extra={"iterations": len(durations)} | (options.extra or {}),
    )
    session.add(run)
    session.flush()

    for sequence, duration_ms in enumerate(durations):
        session.add(
            Result(
                result_id=f"{options.run_id}-result-{sequence}",
                run_id=options.run_id,
                sequence=sequence,
                started_at=options.started_at + dt.timedelta(milliseconds=sequence),
                duration_ms=duration_ms,
            ),
        )

    for offset_s, power_w in options.power_samples or [(0.0, 5.0), (30.0, 5.0)]:
        session.add(
            TelemetrySample(
                run_id=options.run_id,
                timestamp=options.started_at + dt.timedelta(seconds=offset_s),
                source=options.power_source,
                metric=options.power_metric,
                value=power_w,
            ),
        )

    session.commit()
    return run


def _first_run(data: MatrixData) -> dict[str, Any]:
    return data.to_dict()["cells"][0]["runs"][0]


def test_export_single_run_with_latency_and_energy(session: Session, tmp_path: Path) -> None:
    _seed_run(session, durations_ms=[1.0] * 10)

    data = export_matrix(_config(), session, tmp_path / "matrix.yml")
    payload = data.to_dict()

    assert payload["schema_version"] == 1
    assert payload["generated_from_runs"] == 1
    run = payload["cells"][0]["runs"][0]
    assert run["latency_stats"]["n_samples"] == 10
    assert run["latency_stats"]["mean_us"] == pytest.approx(1000.0)
    assert run["energy_stats"]["total_wh"] == pytest.approx(150.0 / 3600.0)
    assert run["energy_stats"]["wh_per_1000"] == pytest.approx(150.0 / 3600.0 / 10 * 1000)
    assert yaml.safe_load((tmp_path / "matrix.yml").read_text())["generated_from_runs"] == 1


def test_energy_denominator_uses_same_untrimmed_run_results_as_integral(
    session: Session,
) -> None:
    durations = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 100.0]
    _seed_run(session, durations_ms=durations)

    run = _first_run(export_matrix(_config(), session, output_path=None))

    # IQR still removes the outlying latency result, but the energy integral
    # spans all ten measured results. Its denominator must therefore remain 10.
    assert run["latency_stats"]["n_samples"] == 9
    assert run["energy_stats"]["wh_per_1000"] == pytest.approx(
        150.0 / 3600.0 / len(durations) * 1000,
    )


def test_export_surfaces_telemetry_partial(session: Session) -> None:
    _seed_run(
        session,
        telemetry_partial=True,
        telemetry_partial_sources=["fnb58"],
    )

    run = _first_run(export_matrix(_config(), session, output_path=None))

    assert run["telemetry_partial"] is True
    assert run["telemetry_partial_sources"] == ["fnb58"]
    assert run["partial_reasons"] == []


def test_export_includes_multiple_runs_per_cell(session: Session) -> None:
    _seed_run(session, run_id="run-1")
    second_start = START + dt.timedelta(minutes=1)
    _seed_run(
        session,
        run_id="run-2",
        started_at=second_start,
        finished_at=second_start + dt.timedelta(seconds=30),
    )

    cell = export_matrix(_config(), session, output_path=None).to_dict()["cells"][0]

    assert cell["status"] == "ok"
    assert cell["eligible_run_count"] == 2
    assert cell["extra_run_count"] == 1
    assert [run["run_id"] for run in cell["runs"]] == ["run-1", "run-2"]


def test_export_marks_cell_incomplete_when_repeat_coverage_is_short(session: Session) -> None:
    _seed_run(session)
    config = _config([{"task": "kws", "target": "f401re", "required_runs": 3}])

    cell = export_matrix(config, session, output_path=None).to_dict()["cells"][0]

    assert cell["status"] == "incomplete"
    assert cell["eligible_run_count"] == 1
    assert cell["missing_run_count"] == 2
    assert cell["coverage_warnings"] == [
        "repeat coverage incomplete: required 3, eligible 1, missing 2",
    ]


def test_export_no_data_cell(session: Session) -> None:
    cell = export_matrix(_config(), session, output_path=None).to_dict()["cells"][0]

    assert cell == {
        "task": "kws",
        "target": "f401re",
        "status": "no_data",
        "required_runs": 1,
        "eligible_run_count": 0,
        "missing_run_count": 1,
        "extra_run_count": 0,
        "ineligible_run_count": 0,
        "coverage_warnings": [
            "repeat coverage incomplete: required 1, eligible 0, missing 1",
        ],
        "runs": [],
    }


def test_export_ignores_db_runs_outside_config(session: Session) -> None:
    _seed_run(session, task="ic", target="nano33")

    data = export_matrix(_config(), session, output_path=None)

    assert data.generated_from_runs == 0
    assert data.cells[0].status == "no_data"


def test_export_handles_run_with_no_result_rows(session: Session) -> None:
    _seed_run(session, durations_ms=[])

    run = _first_run(export_matrix(_config(), session, output_path=None))

    assert run["latency_stats"] is None
    assert run["energy_stats"]["wh_per_1000"] == math.inf
    assert "no measured Result rows" in run["warnings"][0]


def test_export_marks_incomplete_run_without_energy(session: Session) -> None:
    _seed_run(session, finished_at=None, status="running")

    run = _first_run(export_matrix(_config(), session, output_path=None))

    assert run["duration_s"] is None
    assert run["energy_stats"] is None
    assert "finished_at" in run["warnings"][0]


def test_export_preserves_latency_when_energy_is_quarantined(session: Session) -> None:
    _seed_run(
        session,
        extra={
            "energy_quarantined": True,
            "energy_quarantine_reason": "non-conforming power boundary",
        },
    )

    run = _first_run(export_matrix(_config(), session, output_path=None))

    assert run["latency_stats"]["n_samples"] == 10
    assert run["energy_stats"] is None
    assert run["warnings"] == [
        "energy stats quarantined: non-conforming power boundary",
    ]


def test_export_excludes_repeat_quarantined_run_from_coverage(session: Session) -> None:
    _seed_run(
        session,
        run_id="run-1",
        extra={
            "repeat_quarantined": True,
            "repeat_quarantine_reason": "pre-discipline boundary",
        },
    )
    _seed_run(session, run_id="run-2", started_at=START + dt.timedelta(minutes=1))

    cell = export_matrix(_config(), session, output_path=None).to_dict()["cells"][0]

    assert cell["eligible_run_count"] == 1
    assert cell["ineligible_run_count"] == 1
    assert cell["runs"][0]["warnings"] == [
        "repeat stats quarantined: pre-discipline boundary",
    ]


def test_export_handles_naive_datetimes_as_utc(session: Session) -> None:
    naive_start = dt.datetime(2026, 5, 15, 12, 0)
    _seed_run(session, started_at=naive_start, finished_at=naive_start + dt.timedelta(seconds=30))

    run = _first_run(export_matrix(_config(), session, output_path=None))

    assert run["started_at"].endswith("Z")
    assert run["duration_s"] == pytest.approx(30.0)
    assert run["energy_stats"]["telemetry_coverage"] == pytest.approx(1.0)


def test_export_supports_custom_power_source_and_metric(session: Session) -> None:
    _seed_run(
        session,
        power_source="mock_ina219_main",
        power_metric="power",
    )

    run = _first_run(
        export_matrix(
            _config(),
            session,
            output_path=None,
            power_source="mock_ina219_main",
        ),
    )

    assert run["energy_stats"]["avg_power_w"] == pytest.approx(5.0)


def test_export_includes_config_cells_in_order(session: Session) -> None:
    _seed_run(session, task="ic", target="nano33")
    config = _config(
        [
            {"task": "kws", "target": "f401re"},
            {"task": "ic", "target": "nano33"},
        ],
    )

    cells = export_matrix(config, session, output_path=None).to_dict()["cells"]

    assert [(cell["task"], cell["target"], cell["status"]) for cell in cells] == [
        ("kws", "f401re", "no_data"),
        ("ic", "nano33", "ok"),
    ]
