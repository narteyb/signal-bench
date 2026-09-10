# SPDX-License-Identifier: Apache-2.0
"""Tests for partial-aware synth headline aggregation."""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench.schema import Base, Result, Run, Target, Task, TelemetrySample
from signal_bench.synth import cell_detail, cell_headline, filter_non_partial
from signal_bench.synth.chart_data import build_hardware_curve, build_variance_illustration
from signal_bench.synth.matrix_data import CellData, MatrixData, RunData
from signal_bench_cli.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path

START = dt.datetime(2026, 5, 15, 12, 0, tzinfo=dt.UTC)


def _run(
    run_id: str,
    *,
    latency_us: float = 100.0,
    wh_per_1000: float = 0.001,
    partial: bool = False,
    partial_reasons: list[str] | None = None,
) -> RunData:
    return RunData(
        run_id=run_id,
        started_at="2026-05-15T12:00:00Z",
        status="completed",
        duration_s=30.0,
        iterations=100,
        warmup_iterations=10,
        model_hash="hash",
        quantization="int8",
        telemetry_partial=partial,
        telemetry_partial_sources=["fnb58"] if partial else [],
        partial_reasons=partial_reasons
        or (["fnb58: coverage=72%, threshold=90%, samples=1080/1500"] if partial else []),
        latency_stats={
            "n_samples": 100,
            "n_outliers": 0,
            "mean_us": latency_us,
            "median_us": latency_us,
            "p95_us": latency_us * 1.1,
            "p99_us": latency_us * 1.2,
            "stddev_us": latency_us * 0.05,
            "variance_pct": 5.0,
            "min_us": latency_us * 0.9,
            "max_us": latency_us * 1.2,
        },
        energy_stats={
            "total_wh": wh_per_1000 / 1000,
            "avg_power_w": 5.0,
            "sample_count": 30,
            "duration_s": 30.0,
            "telemetry_coverage": 1.0,
            "wh_per_1000": wh_per_1000,
            "warnings": [],
            "min_power_w": 5.0,
            "max_power_w": 5.0,
        },
    )


def _cell(runs: list[RunData]) -> CellData:
    return CellData(task="kws", target="f401re", status="ok" if runs else "no_data", runs=runs)


def _matrix(runs: list[RunData]) -> MatrixData:
    return MatrixData(
        schema_version=1,
        matrix_name="partial-test",
        generated_at="2026-05-15T12:00:00Z",
        generated_from_runs=len(runs),
        cells=[_cell(runs)],
    )


def test_cell_with_five_non_partial_runs_aggregates_over_all_five() -> None:
    runs = [_run(f"run-{index}", latency_us=100 + index) for index in range(5)]

    assert filter_non_partial(runs) == runs
    assert cell_headline(runs, "latency_us") == 102.0
    detail = cell_detail(runs)
    assert detail.n_total == 5
    assert detail.n_partial == 0
    assert detail.headline_basis == 5
    assert all(not run.partial for run in detail.runs)


def test_cell_with_mixed_partial_runs_aggregates_over_non_partial_subset() -> None:
    runs = [
        _run("good-1", latency_us=100),
        _run("partial-1", latency_us=10, partial=True),
        _run("good-2", latency_us=110),
        _run("partial-2", latency_us=1000, partial=True),
        _run("good-3", latency_us=120),
    ]

    assert [run.run_id for run in filter_non_partial(runs)] == ["good-1", "good-2", "good-3"]
    assert cell_headline(runs, "latency_us") == 110.0
    detail = cell_detail(runs)
    assert detail.n_total == 5
    assert detail.n_partial == 2
    assert detail.headline_basis == 3
    assert [run.partial for run in detail.runs] == [False, True, False, True, False]


def test_all_partial_cell_has_null_headline_but_preserves_detail() -> None:
    runs = [
        _run("partial-1", partial=True),
        _run("partial-2", partial=True),
        _run("partial-3", partial=True),
    ]

    assert cell_headline(runs, "latency_us") is None
    detail = cell_detail(runs)
    assert detail.n_total == 3
    assert detail.n_partial == 3
    assert detail.headline_basis == 0
    assert all(run.partial for run in detail.runs)


def test_no_data_cell_is_distinct_from_all_partial_cell() -> None:
    detail = cell_detail([])

    assert cell_headline([], "latency_us") is None
    assert detail.n_total == 0
    assert detail.n_partial == 0
    assert detail.headline_basis == 0


def test_median_uses_non_partial_subset_only() -> None:
    runs = [
        _run("good-1", latency_us=10),
        _run("partial", latency_us=999, partial=True),
        _run("good-2", latency_us=20),
    ]

    assert cell_headline(runs, "latency_us", statistic="median") == 15.0


def test_stddev_uses_non_partial_subset_only() -> None:
    runs = [
        _run("good-1", latency_us=10),
        _run("partial", latency_us=999, partial=True),
        _run("good-2", latency_us=20),
    ]

    assert cell_headline(runs, "latency_us", statistic="stddev") == pytest.approx(7.0710678119)


def test_headline_basis_matches_total_minus_partial() -> None:
    runs = [_run("good"), _run("partial-1", partial=True), _run("partial-2", partial=True)]
    detail = cell_detail(runs)

    assert detail.headline_basis == detail.n_total - detail.n_partial


def test_chart_data_emits_partial_marker_and_reasons_per_run() -> None:
    chart = build_variance_illustration(
        _matrix([_run("good"), _run("partial", partial=True)]),
        target="f401re",
    )

    runs = chart["data"]["datasets"][0]["data"]
    assert runs[0]["partial"] is False
    assert runs[0]["partialReasons"] == []
    assert runs[1]["partial"] is True
    assert runs[1]["partialReasons"][0].startswith("fnb58: coverage=")
    assert chart["meta"]["nPartial"] == 1
    assert chart["meta"]["headlineBasis"] == 1


def test_null_headline_propagates_to_chart_json_as_json_null(tmp_path: Path) -> None:
    chart = build_hardware_curve(_matrix([_run("partial", partial=True)]))
    path = tmp_path / "hardware-curve.json"
    path.write_text(json.dumps(chart), encoding="utf-8")

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["data"]["datasets"][0]["data"] == [None]


def test_matrix_yaml_preserves_actual_null_not_string_null(tmp_path: Path) -> None:
    chart = build_hardware_curve(_matrix([_run("partial", partial=True)]))
    path = tmp_path / "chart.yml"
    path.write_text(yaml.safe_dump(chart), encoding="utf-8")

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded["data"]["datasets"][0]["data"] == [None]


def test_synth_report_cli_surfaces_partial_summary_lines(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.yaml"
    db_path = tmp_path / "signal-bench.db"
    output_yaml = tmp_path / "matrix.yml"
    output_report = tmp_path / "report.md"
    output_charts = tmp_path / "charts"
    _write_matrix_config(matrix_path)
    _seed_cli_db(db_path)

    result = CliRunner().invoke(
        main,
        [
            "synth",
            "report",
            "--matrix-config",
            str(matrix_path),
            "--db",
            str(db_path),
            "--output-yaml",
            str(output_yaml),
            "--output-report",
            str(output_report),
            "--output-charts",
            str(output_charts),
            "--skip-charts",
            "--skip-report",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "partial=1, headline_basis=1" in result.output
    assert "Partial reason sources: fnb58=1" in result.output
    payload = yaml.safe_load(output_yaml.read_text(encoding="utf-8"))
    assert payload["cells"][0]["runs"][1]["partial_reasons"][0].startswith("fnb58:")


def _write_matrix_config(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "partial-cli",
                "version": "1.0.0",
                "description": "Partial aggregation CLI fixture.",
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
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _seed_cli_db(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    try:
        with maker() as session:
            _seed_db_run(session, run_id="good", latency_ms=1.0, partial=False)
            _seed_db_run(session, run_id="partial", latency_ms=100.0, partial=True)
    finally:
        engine.dispose()


def _seed_db_run(session: Session, *, run_id: str, latency_ms: float, partial: bool) -> None:
    target = session.get(Target, "target-f401re") or Target(
        target_id="target-f401re",
        name="f401re",
        kind="mcu",
    )
    task = session.get(Task, "task-kws") or Task(
        task_id="task-kws",
        name="kws",
        version="test",
    )
    session.add_all([target, task])
    session.flush()
    run = Run(
        run_id=run_id,
        target_id=target.target_id,
        task_id=task.task_id,
        started_at=START,
        finished_at=START + dt.timedelta(seconds=30),
        status="completed",
        corpus_tag="X",
        warmup_count=0,
        measurement_count=3,
        signal_bench_version="test",
        model_name="kws",
        model_hash="hash-kws",
        quantization="int8",
        telemetry_partial=partial,
        telemetry_partial_sources=["fnb58"] if partial else None,
        partial_reasons=(
            ["fnb58: coverage=72%, threshold=90%, samples=1080/1500"] if partial else None
        ),
    )
    session.add(run)
    session.flush()
    for sequence in range(3):
        session.add(
            Result(
                result_id=f"{run_id}-result-{sequence}",
                run_id=run_id,
                sequence=sequence,
                started_at=START + dt.timedelta(milliseconds=sequence),
                duration_ms=latency_ms,
            ),
        )
    for offset_s in (0.0, 30.0):
        session.add(
            TelemetrySample(
                run_id=run_id,
                timestamp=START + dt.timedelta(seconds=offset_s),
                source="fnb58",
                metric="power",
                value=5.0,
            ),
        )
    session.commit()
