# SPDX-License-Identifier: Apache-2.0
"""Tests for partial-run-aware inference warning export."""

from __future__ import annotations

import datetime as dt
import warnings
from typing import TYPE_CHECKING

import yaml
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench.analysis.timing import inference_coverage
from signal_bench.schema import Base, Result, Run, Target, Task, TelemetrySample
from signal_bench.synth import cell_detail
from signal_bench.synth.chart_data import build_variance_illustration
from signal_bench.synth.exporter import export_matrix
from signal_bench.synth.matrix_config import MatrixConfig
from signal_bench_cli.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path

START = dt.datetime(2026, 5, 15, 12, 0, tzinfo=dt.UTC)


def _config() -> MatrixConfig:
    return MatrixConfig.model_validate(
        {
            "schema_version": 1,
            "name": "partial-warning-test",
            "version": "1.0.0",
            "description": "Partial warning fixture.",
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
    telemetry_partial: bool,
    result_count: int = 4,
    covered_sequences: set[int] | None = None,
) -> None:
    target = session.get(Target, "target-f401re") or Target(
        target_id="target-f401re",
        name="f401re",
        kind="mcu",
    )
    task = session.get(Task, "task-kws") or Task(task_id="task-kws", name="kws", version="test")
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
        measurement_count=result_count,
        signal_bench_version="test",
        model_name="kws",
        model_hash="hash-kws",
        quantization="int8",
        telemetry_partial=telemetry_partial,
        telemetry_partial_sources=["fnb58"] if telemetry_partial else None,
        partial_reasons=(
            ["fnb58: coverage=72%, threshold=90%, samples=1080/1500"] if telemetry_partial else None
        ),
    )
    session.add(run)
    session.flush()
    covered = covered_sequences if covered_sequences is not None else set(range(result_count))
    for sequence in range(result_count):
        started_at = START + dt.timedelta(milliseconds=sequence * 10)
        session.add(
            Result(
                result_id=f"{run_id}-result-{sequence}",
                run_id=run_id,
                sequence=sequence,
                started_at=started_at,
                duration_ms=5.0,
            ),
        )
        if sequence in covered:
            session.add(
                TelemetrySample(
                    run_id=run_id,
                    timestamp=started_at + dt.timedelta(milliseconds=1),
                    source="fnb58",
                    metric="power",
                    value=5.0,
                ),
            )
    # Preserve run-level energy even when a subset of inference windows is empty.
    for offset_s in (1.0, 30.0):
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


def _first_run(session: Session) -> dict:
    return export_matrix(_config(), session, output_path=None).to_dict()["cells"][0]["runs"][0]


def test_non_partial_run_has_no_partial_inference_warnings(session: Session) -> None:
    _seed_run(session, run_id="clean", telemetry_partial=False, covered_sequences={0, 1, 2, 3})

    run = _first_run(session)

    assert run["partial_inference_warnings"] == []


def test_partial_run_with_all_windows_covered_has_no_warnings(session: Session) -> None:
    _seed_run(session, run_id="covered", telemetry_partial=True, covered_sequences={0, 1, 2, 3})

    run = _first_run(session)

    assert run["partial_inference_warnings"] == []


def test_partial_run_with_some_empty_windows_records_warning_entries(session: Session) -> None:
    _seed_run(session, run_id="mixed", telemetry_partial=True, covered_sequences={0, 2})

    run = _first_run(session)

    assert run["partial_inference_warnings"] == [
        {"inference_id": 1, "source": "fnb58"},
        {"inference_id": 3, "source": "fnb58"},
    ]


def test_partial_run_with_all_empty_windows_records_all_inferences(session: Session) -> None:
    _seed_run(session, run_id="empty", telemetry_partial=True, covered_sequences=set())

    run = _first_run(session)

    assert run["partial_inference_warnings"] == [
        {"inference_id": 0, "source": "fnb58"},
        {"inference_id": 1, "source": "fnb58"},
        {"inference_id": 2, "source": "fnb58"},
        {"inference_id": 3, "source": "fnb58"},
    ]


def test_warning_capture_isolated_between_runs(session: Session) -> None:
    _seed_run(session, run_id="empty", telemetry_partial=True, covered_sequences=set())
    _seed_run(session, run_id="covered", telemetry_partial=True, covered_sequences={0, 1, 2, 3})

    runs = export_matrix(_config(), session, output_path=None).to_dict()["cells"][0]["runs"]

    assert len(runs[0]["partial_inference_warnings"]) == 4
    assert runs[1]["partial_inference_warnings"] == []


def test_cell_detail_sums_partial_inference_count(session: Session) -> None:
    _seed_run(session, run_id="first", telemetry_partial=True, covered_sequences={0})
    _seed_run(session, run_id="second", telemetry_partial=True, covered_sequences={0, 1, 2})
    cell = export_matrix(_config(), session, output_path=None).cells[0]

    detail = cell_detail(cell.runs)

    assert detail.partial_inference_count == 4


def test_chart_data_emits_partial_inference_warning_metadata(session: Session) -> None:
    _seed_run(session, run_id="mixed", telemetry_partial=True, covered_sequences={0, 2})
    matrix_data = export_matrix(_config(), session, output_path=None)

    chart = build_variance_illustration(matrix_data, target="f401re")

    point = chart["data"]["datasets"][0]["data"][0]
    assert point["partialInferenceWarnings"] == [
        {"inference_id": 1, "source": "fnb58"},
        {"inference_id": 3, "source": "fnb58"},
    ]
    assert chart["meta"]["partialInferenceCount"] == 2


def test_yaml_export_renders_warning_shape_and_null_cleanly(tmp_path: Path) -> None:
    payload = {
        "variance_strip_tier1": {
            "cells": [
                {
                    "partial_inference_count": 1,
                    "runs": [
                        {
                            "value": None,
                            "partial": True,
                            "partial_inference_warnings": [
                                {"inference_id": 3, "source": "fnb58"},
                            ],
                        },
                    ],
                },
            ],
        },
    }
    path = tmp_path / "shape.yml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))

    run = loaded["variance_strip_tier1"]["cells"][0]["runs"][0]
    assert run["value"] is None
    assert run["partial_inference_warnings"] == [{"inference_id": 3, "source": "fnb58"}]


def test_inference_coverage_diagnostic_does_not_emit_partial_warning(session: Session) -> None:
    _seed_run(session, run_id="mixed", telemetry_partial=True, covered_sequences={0, 2})

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        report = inference_coverage(session, "mixed", "fnb58")

    assert report.missing_inferences == 2
    assert captured == []


def test_cli_emits_partial_inference_line_only_when_count_positive(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.yaml"
    db_path = tmp_path / "signal-bench.db"
    output_yaml = tmp_path / "matrix.yml"
    output_report = tmp_path / "report.md"
    output_charts = tmp_path / "charts"
    matrix_path.write_text(yaml.safe_dump(_config().model_dump(mode="json"), sort_keys=False))
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

    assert result.exit_code == 1, result.output
    assert "Partial inference windows: 2 (fnb58: 2)" in result.output


def _seed_cli_db(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    try:
        with maker() as session:
            _seed_run(session, run_id="mixed", telemetry_partial=True, covered_sequences={0, 2})
    finally:
        engine.dispose()
