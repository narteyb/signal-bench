# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import yaml
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench.schema import Base, Result, Run, Target, Task, TelemetrySample
from signal_bench_cli.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path

START = dt.datetime(2026, 5, 15, 12, 0, tzinfo=dt.UTC)


def _write_matrix_config(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "post-1-test",
                "version": "1.0.0",
                "description": "CLI integration test matrix.",
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


def _seed_db(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    try:
        with maker() as session:
            _seed_run(session)
    finally:
        engine.dispose()


def _seed_run(session: Session) -> None:
    target = Target(target_id="target-f401re", name="f401re", kind="mcu")
    task = Task(task_id="task-kws", name="kws", version="mlperf-tiny-v1.3")
    session.add_all([target, task])
    session.flush()
    run = Run(
        run_id="run-1",
        target_id=target.target_id,
        task_id=task.task_id,
        started_at=START,
        finished_at=START + dt.timedelta(seconds=30),
        status="completed",
        corpus_tag="X",
        warmup_count=0,
        measurement_count=10,
        signal_bench_version="test",
        model_name="kws",
        model_hash="hash-kws",
        quantization="int8",
        telemetry_partial=False,
    )
    session.add(run)
    session.flush()
    for sequence in range(10):
        session.add(
            Result(
                result_id=f"result-{sequence}",
                run_id=run.run_id,
                sequence=sequence,
                started_at=START + dt.timedelta(milliseconds=sequence),
                duration_ms=1.0,
            ),
        )
    for offset_s in (0.0, 10.0, 20.0, 30.0):
        session.add(
            TelemetrySample(
                run_id=run.run_id,
                timestamp=START + dt.timedelta(seconds=offset_s),
                source="fnb58",
                metric="power",
                value=5.0,
            ),
        )
    session.commit()


def test_synth_report_help_is_registered() -> None:
    runner = CliRunner()

    assert runner.invoke(main, ["--help"]).exit_code == 0
    synth_help = runner.invoke(main, ["synth", "--help"])
    report_help = runner.invoke(main, ["synth", "report", "--help"])

    assert synth_help.exit_code == 0
    assert "report" in synth_help.output
    assert report_help.exit_code == 0
    assert "--matrix-config" in report_help.output
    assert "--skip-charts" in report_help.output


def test_synth_report_generates_all_outputs(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.yaml"
    db_path = tmp_path / "signal-bench.db"
    output_yaml = tmp_path / "data" / "post-1-data.yml"
    output_charts = tmp_path / "charts"
    output_report = tmp_path / "report.md"
    _write_matrix_config(matrix_path)
    _seed_db(db_path)

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
            "--output-charts",
            str(output_charts),
            "--output-report",
            str(output_report),
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Status: OK=1" in result.output
    assert output_yaml.exists()
    assert (output_charts / "hardware-curve.json").exists()
    assert (output_charts / "wh-comparison.json").exists()
    assert (output_charts / "variance-illustration.json").exists()
    assert output_report.exists()
    payload = yaml.safe_load(output_yaml.read_text(encoding="utf-8"))
    assert payload["generated_from_runs"] == 1
    assert "post-1-test Synth Report" in output_report.read_text(encoding="utf-8")


def test_synth_report_skip_flags(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.yaml"
    db_path = tmp_path / "signal-bench.db"
    output_yaml = tmp_path / "post-1-data.yml"
    output_charts = tmp_path / "charts"
    output_report = tmp_path / "report.md"
    _write_matrix_config(matrix_path)
    _seed_db(db_path)

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
            "--output-charts",
            str(output_charts),
            "--output-report",
            str(output_report),
            "--skip-charts",
            "--skip-report",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_yaml.exists()
    assert not output_charts.exists()
    assert not output_report.exists()


def test_synth_report_missing_config_exits_config_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        [
            "synth",
            "report",
            "--matrix-config",
            str(tmp_path / "missing.yaml"),
            "--db",
            str(tmp_path / "missing.db"),
        ],
    )

    assert result.exit_code == 3
    assert "Matrix config not found" in result.output
    assert "Hint:" in result.output
