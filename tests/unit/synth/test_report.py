# SPDX-License-Identifier: Apache-2.0
"""Tests for markdown synthesis report rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from signal_bench.synth.matrix_data import CellData, MatrixData, RunData
from signal_bench.synth.report import (
    cell_status,
    find_latency_outliers,
    render_markdown_report,
    status_counts,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Options for report test run fixtures."""

    status: str = "completed"
    duration_s: float | None = 30.0
    telemetry_partial: bool = False
    median_us: float = 100.0
    p95_us: float = 120.0
    wh_per_1000: float = 0.001


def _run(run_id: str, **overrides: object) -> RunData:
    options = RunOptions(**overrides)
    return RunData(
        run_id=run_id,
        started_at="2026-05-15T12:00:00Z",
        status=options.status,
        duration_s=options.duration_s,
        iterations=100,
        warmup_iterations=10,
        model_hash="hash",
        quantization="int8",
        telemetry_partial=options.telemetry_partial,
        telemetry_partial_sources=["fnb58"] if options.telemetry_partial else [],
        latency_stats={
            "n_samples": 100,
            "n_outliers": 0,
            "mean_us": options.median_us,
            "median_us": options.median_us,
            "p95_us": options.p95_us,
            "p99_us": options.p95_us * 1.1,
            "stddev_us": 5.0,
            "variance_pct": 5.0,
            "min_us": options.median_us * 0.9,
            "max_us": options.p95_us,
        },
        energy_stats={
            "total_wh": options.wh_per_1000 / 1000,
            "avg_power_w": 5.0,
            "sample_count": 300,
            "duration_s": 30.0,
            "telemetry_coverage": 1.0,
            "wh_per_1000": options.wh_per_1000,
            "warnings": [],
            "min_power_w": 4.8,
            "max_power_w": 5.2,
        },
    )


def _matrix(cells: list[CellData]) -> MatrixData:
    return MatrixData(
        schema_version=1,
        matrix_name="test-matrix",
        generated_at="2026-05-15T12:00:00Z",
        generated_from_runs=sum(len(cell.runs) for cell in cells),
        cells=cells,
    )


def test_cell_status_taxonomy() -> None:
    assert cell_status(CellData(task="kws", target="pi5", status="no_data", runs=[])) == "NO_DATA"
    assert (
        cell_status(
            CellData(task="kws", target="pi5", status="ok", runs=[_run("run", duration_s=None)]),
        )
        == "INCOMPLETE"
    )
    assert (
        cell_status(
            CellData(
                task="kws",
                target="pi5",
                status="ok",
                runs=[_run("run", telemetry_partial=True)],
            ),
        )
        == "PARTIAL"
    )
    assert cell_status(CellData(task="kws", target="pi5", status="ok", runs=[_run("run")])) == "OK"


def test_cell_status_ignores_failed_attempt_when_repeat_coverage_is_complete() -> None:
    assert (
        cell_status(
            CellData(
                task="kws",
                target="pi5",
                status="ok",
                runs=[_run("accepted"), _run("failed", status="failed")],
                required_runs=1,
                eligible_run_count=1,
                ineligible_run_count=1,
            ),
        )
        == "OK"
    )


def test_cell_status_ignores_partial_diagnostic_when_repeat_coverage_is_complete() -> None:
    assert (
        cell_status(
            CellData(
                task="kws",
                target="pi5",
                status="ok",
                runs=[_run("accepted"), _run("partial", telemetry_partial=True)],
                required_runs=1,
                eligible_run_count=1,
                ineligible_run_count=1,
            ),
        )
        == "OK"
    )


def test_status_counts() -> None:
    counts = status_counts(
        _matrix(
            [
                CellData(task="kws", target="pi5", status="ok", runs=[_run("ok")]),
                CellData(task="ic", target="pi5", status="no_data", runs=[]),
            ],
        ),
    )

    assert counts["OK"] == 1
    assert counts["NO_DATA"] == 1


def test_find_latency_outliers() -> None:
    outliers = find_latency_outliers(
        _matrix(
            [
                CellData(
                    task="kws",
                    target="pi5",
                    status="ok",
                    runs=[
                        _run("normal", median_us=100, p95_us=120),
                        _run("tail", median_us=105, p95_us=300),
                    ],
                ),
            ],
        ),
        threshold=2.0,
    )

    assert [outlier.run_id for outlier in outliers] == ["tail"]


def test_render_empty_matrix_report() -> None:
    markdown = render_markdown_report(_matrix([]), output_path=None)

    assert "# test-matrix Synth Report" in markdown
    assert "Cells: `0`" in markdown
    assert "No latency p95 outliers" in markdown


def test_render_full_report_contains_sections_and_chart_refs(tmp_path: Path) -> None:
    output_path = tmp_path / "report.md"
    markdown = render_markdown_report(
        _matrix([CellData(task="kws", target="pi5", status="ok", runs=[_run("run-1")])]),
        output_path,
        chart_dir=tmp_path / "charts",
    )

    assert output_path.read_text(encoding="utf-8") == markdown
    assert "## Summary Matrix" in markdown
    assert "## Per-Cell Detail" in markdown
    assert "## Charts" in markdown
    assert "hardware-curve.json" in markdown


def test_render_report_notes_skipped_charts() -> None:
    markdown = render_markdown_report(
        _matrix([CellData(task="kws", target="pi5", status="ok", runs=[_run("run-1")])]),
        chart_dir=None,
    )

    assert "Chart generation was skipped." in markdown
