# SPDX-License-Identifier: Apache-2.0
"""Markdown report rendering for synthesized matrix data."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from signal_bench.synth._partial import cell_detail, cell_headline, repeat_quarantined
from signal_bench.synth.chart_data import TARGET_LABELS, TARGET_ORDER, TASK_ORDER

if TYPE_CHECKING:
    from signal_bench.synth.matrix_data import CellData, MatrixData, RunData

LARGE_NUMBER_THRESHOLD = 100
MEDIUM_NUMBER_THRESHOLD = 10


@dataclass(frozen=True, slots=True)
class OutlierRun:
    """One run whose latency tail is large relative to its cell median."""

    task: str
    target: str
    run_id: str
    median_us: float
    p95_us: float
    ratio: float


def render_markdown_report(
    matrix_data: MatrixData,
    output_path: str | Path | None = None,
    *,
    chart_dir: str | Path | None = "data/charts",
    outlier_threshold: float = 2.0,
) -> str:
    """Render a markdown report and optionally write it to disk."""
    markdown = _build_markdown(
        matrix_data,
        chart_dir=Path(chart_dir) if chart_dir is not None else None,
        outlier_threshold=outlier_threshold,
    )
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
    return markdown


def cell_status(cell: CellData) -> str:
    """Return report status for one exported cell."""
    if not cell.runs:
        return "NO_DATA"
    if cell.missing_run_count:
        return "INCOMPLETE"
    if any(run.duration_s is None or run.status == "running" for run in cell.runs):
        return "INCOMPLETE"
    if any(run.telemetry_partial for run in cell.runs):
        if cell.required_runs and cell.eligible_run_count >= cell.required_runs:
            return "OK"
        return "PARTIAL"
    return "OK"


def status_counts(matrix_data: MatrixData) -> Counter[str]:
    """Return counts by report status."""
    return Counter(cell_status(cell) for cell in matrix_data.cells)


def find_latency_outliers(
    matrix_data: MatrixData,
    *,
    threshold: float = 2.0,
) -> list[OutlierRun]:
    """Return runs whose p95 latency exceeds threshold times cell median latency."""
    outliers: list[OutlierRun] = []
    for cell in matrix_data.cells:
        cell_median = cell_headline(cell.runs, "latency_us")
        if cell_median is None:
            continue
        if cell_median <= 0:
            continue
        for run in cell.runs:
            if repeat_quarantined(run):
                continue
            if run.latency_stats is None:
                continue
            p95 = float(run.latency_stats["p95_us"])
            ratio = p95 / cell_median
            if ratio > threshold:
                outliers.append(
                    OutlierRun(
                        task=cell.task,
                        target=cell.target,
                        run_id=run.run_id,
                        median_us=float(run.latency_stats["median_us"]),
                        p95_us=p95,
                        ratio=ratio,
                    ),
                )
    return outliers


def _build_markdown(
    matrix_data: MatrixData,
    *,
    chart_dir: Path | None,
    outlier_threshold: float,
) -> str:
    lines: list[str] = []
    counts = status_counts(matrix_data)
    lines.extend(
        [
            f"# {matrix_data.matrix_name} Synth Report",
            "",
            f"- Generated: `{matrix_data.generated_at}`",
            f"- Cells: `{len(matrix_data.cells)}`",
            f"- Runs: `{matrix_data.generated_from_runs}`",
            f"- Repeat coverage: `{_repeat_coverage_summary(matrix_data)}`",
            "- Status: "
            + ", ".join(
                f"{status}={counts.get(status, 0)}"
                for status in ("OK", "PARTIAL", "INCOMPLETE", "NO_DATA")
            ),
            "",
            "## Summary Matrix",
            "",
        ],
    )
    lines.extend(_summary_table(matrix_data))
    lines.extend(["", "## Per-Cell Detail", ""])
    for cell in matrix_data.cells:
        lines.extend(_cell_detail(cell))
    lines.extend(["", "## Outliers", ""])
    outliers = find_latency_outliers(matrix_data, threshold=outlier_threshold)
    if outliers:
        lines.extend(
            [
                "| Task | Target | Run | Median us | P95 us | Ratio |",
                "|---|---|---|---:|---:|---:|",
            ],
        )
        lines.extend(
            (
                f"| {outlier.task} | {outlier.target} | `{outlier.run_id}` | "
                f"{outlier.median_us:.2f} | {outlier.p95_us:.2f} | "
                f"{outlier.ratio:.2f}x |"
            )
            for outlier in outliers
        )
    else:
        lines.append(f"No latency p95 outliers above {outlier_threshold:.2f}x cell median.")
    lines.extend(["", "## Charts", ""])
    lines.extend(_chart_references(chart_dir))
    return "\n".join(lines).rstrip() + "\n"


def _summary_table(matrix_data: MatrixData) -> list[str]:
    targets = _targets_in_order(matrix_data)
    lines = [
        "| Task | " + " | ".join(_target_label(target) for target in targets) + " |",
        "|---|" + "|".join("---" for _ in targets) + "|",
    ]
    for task in _tasks_in_order(matrix_data):
        cells = []
        for target in targets:
            cell = _find_cell(matrix_data, task=task, target=target)
            cells.append(_summary_cell(cell) if cell is not None else "NO_DATA")
        lines.append(f"| {task} | " + " | ".join(cells) + " |")
    return lines


def _summary_cell(cell: CellData) -> str:
    status = cell_status(cell)
    if status == "NO_DATA":
        return status
    latency = cell_headline(cell.runs, "latency_us")
    energy = cell_headline(cell.runs, "wh_per_1000_mwh")
    return f"{status}<br>{_format_optional(latency)} us<br>{_format_optional(energy)} mWh"


def _cell_detail(cell: CellData) -> list[str]:
    lines = [
        f"### {cell.task}/{cell.target}",
        "",
        f"- Status: `{cell_status(cell)}`",
        f"- Runs: `{len(cell.runs)}`",
        (
            f"- Repeat coverage: `{cell.eligible_run_count}` eligible of "
            f"`{cell.required_runs}` required"
        ),
    ]
    if cell.missing_run_count:
        lines.append(f"- Missing repeat runs: `{cell.missing_run_count}`")
    if cell.ineligible_run_count:
        lines.append(f"- Ineligible runs: `{cell.ineligible_run_count}`")
    if cell.extra_run_count:
        lines.append(f"- Extra eligible runs: `{cell.extra_run_count}`")
    if cell.coverage_warnings:
        lines.append(
            "- Coverage warnings: "
            + "; ".join(f"`{warning}`" for warning in cell.coverage_warnings),
        )
    if not cell.runs:
        lines.extend(["", "No runs exported for this cell.", ""])
        return lines
    detail = cell_detail(cell.runs)
    lines.append(
        f"- Partial runs: `{detail.n_partial}` of `{detail.n_total}`; "
        f"headline basis: `{detail.headline_basis}`",
    )
    if detail.partial_inference_count:
        lines.append(f"- Partial inference windows: `{detail.partial_inference_count}`")
    if detail.n_total and detail.headline_basis == 0:
        lines.append("- Headline values: `null` because all runs in this cell are partial")

    for run in cell.runs:
        lines.extend(_run_detail(run))
    return lines


def _run_detail(run: RunData) -> list[str]:
    lines = [
        "",
        f"#### Run `{run.run_id}`",
        "",
        f"- Status: `{run.status}`",
        f"- Started: `{run.started_at}`",
        f"- Duration: `{_format_optional(run.duration_s)} s`",
        f"- Iterations: `{run.iterations}` measured, `{run.warmup_iterations}` warmup",
        f"- Telemetry partial: `{run.telemetry_partial}`",
    ]
    if run.telemetry_partial_sources:
        lines.append(f"- Telemetry partial sources: `{', '.join(run.telemetry_partial_sources)}`")
    if run.partial_reasons:
        partial_reason_text = "; ".join(f"`{reason}`" for reason in run.partial_reasons)
        lines.append(f"- Partial reasons: {partial_reason_text}")
    if run.partial_inference_warnings:
        lines.append(f"- Partial inference warnings: `{len(run.partial_inference_warnings)}`")
    if run.latency_stats is not None:
        lines.append(
            "- Latency: median `{median}` us, mean `{mean}` us, p95 `{p95}` us, "
            "p99 `{p99}` us, stddev `{stddev}` us, variance `{variance}%`".format(
                median=_format_number(run.latency_stats["median_us"]),
                mean=_format_number(run.latency_stats["mean_us"]),
                p95=_format_number(run.latency_stats["p95_us"]),
                p99=_format_number(run.latency_stats["p99_us"]),
                stddev=_format_number(run.latency_stats["stddev_us"]),
                variance=_format_number(run.latency_stats["variance_pct"]),
            ),
        )
    else:
        lines.append("- Latency: `unavailable`")
    if run.energy_stats is not None:
        lines.append(
            "- Energy: `{wh}` Wh total, `{mwh}` mWh/1000, avg power `{power}` W, "
            "coverage `{coverage}%`".format(
                wh=_format_number(run.energy_stats["total_wh"]),
                mwh=_format_number(float(run.energy_stats["wh_per_1000"]) * 1000),
                power=_format_number(run.energy_stats["avg_power_w"]),
                coverage=_format_number(float(run.energy_stats["telemetry_coverage"]) * 100),
            ),
        )
    else:
        lines.append("- Energy: `unavailable`")
    warnings = list(run.warnings)
    if run.energy_stats is not None:
        warnings.extend(str(item) for item in run.energy_stats.get("warnings", []))
    if warnings:
        lines.append("- Warnings: " + "; ".join(f"`{warning}`" for warning in warnings))
    return lines


def _chart_references(chart_dir: Path | None) -> list[str]:
    if chart_dir is None:
        return ["Chart generation was skipped."]
    return [
        f"- Hardware curve: `{chart_dir / 'hardware-curve.json'}`",
        f"- Wh comparison: `{chart_dir / 'wh-comparison.json'}`",
        f"- Variance illustration: `{chart_dir / 'variance-illustration.json'}`",
        f"- Hardware curve (Tier 1): `{chart_dir / 'hardware-curve-tier1.json'}`",
        f"- Wh comparison (Tier 1): `{chart_dir / 'wh-comparison-tier1.json'}`",
        f"- Variance strip (Tier 1): `{chart_dir / 'variance-strip-tier1.json'}`",
    ]


def _repeat_coverage_summary(matrix_data: MatrixData) -> str:
    required = sum(cell.required_runs for cell in matrix_data.cells)
    eligible = sum(cell.eligible_run_count for cell in matrix_data.cells)
    missing = sum(cell.missing_run_count for cell in matrix_data.cells)
    return f"{eligible}/{required} eligible runs, {missing} missing"


def _targets_in_order(matrix_data: MatrixData) -> list[str]:
    present = {cell.target for cell in matrix_data.cells}
    ordered = [target for target in TARGET_ORDER if target in present]
    return ordered + sorted(present - set(TARGET_ORDER))


def _tasks_in_order(matrix_data: MatrixData) -> list[str]:
    present = {cell.task for cell in matrix_data.cells}
    ordered = [task for task in TASK_ORDER if task in present]
    return ordered + sorted(present - set(TASK_ORDER))


def _find_cell(matrix_data: MatrixData, *, task: str, target: str) -> CellData | None:
    for cell in matrix_data.cells:
        if cell.task == task and cell.target == target:
            return cell
    return None


def _target_label(target: str) -> str:
    return TARGET_LABELS.get(target, target)


def _format_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _format_number(value)


def _format_number(value: object) -> str:
    if not isinstance(value, int | float | str):
        return "n/a"
    numeric = float(value)
    if math.isnan(numeric):
        return "n/a"
    if math.isinf(numeric):
        return "inf"
    if abs(numeric) >= LARGE_NUMBER_THRESHOLD:
        return f"{numeric:.1f}"
    if abs(numeric) >= MEDIUM_NUMBER_THRESHOLD:
        return f"{numeric:.2f}"
    return f"{numeric:.4f}"
