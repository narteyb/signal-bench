# SPDX-License-Identifier: Apache-2.0
"""Cross-runtime Phase 1 comparison report emission."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self

from signal_bench.phase1.report import Phase1Report, summary_metrics

MOCK_ENERGY_NOTE = (
    "Energy values in this host-only comparison come from deterministic mock telemetry. "
    "They validate harness plumbing and are not physical measurements."
)
MEASUREMENT_PROTOCOL = (
    "warm_steady_state_v1: each runtime loads a resident model and completes one "
    "unmeasured warmup before telemetry starts; TTFT and tokens/s are measured only "
    "for steady-state prompt generation. The v02 comparison is superseded because "
    "llama.cpp then paid per-prompt process startup and model-load costs."
)


@dataclass(frozen=True, slots=True)
class RuntimeComparisonRow:
    """One runtime row in a host comparison."""

    runtime: str
    backend: str
    version: str
    model_name: str
    model_revision: str
    quantization: str | None
    mean_tokens_per_second: float
    median_first_token_ms: float | None
    peak_memory_mb: float | None
    accuracy_score: float
    accuracy_passed: int
    accuracy_total: int
    mock_joules_per_token: float | None
    cross_check_reason: str
    report_path: str
    execution_note: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeComparisonReport:
    """A reproducible comparison across host runtimes."""

    schema_version: int
    comparison_id: str
    model_name: str
    workload_id: str
    energy_basis: str
    energy_note: str
    measurement_protocol: str
    rows: tuple[RuntimeComparisonRow, ...]
    environment: dict[str, Any]

    def to_dict(self: Self) -> dict[str, Any]:
        """Return JSON-serializable comparison data."""
        return {
            "schema_version": self.schema_version,
            "comparison_id": self.comparison_id,
            "model_name": self.model_name,
            "workload_id": self.workload_id,
            "energy_basis": self.energy_basis,
            "energy_note": self.energy_note,
            "measurement_protocol": self.measurement_protocol,
            "rows": [asdict(row) for row in self.rows],
            "environment": self.environment,
        }


def build_runtime_comparison(
    comparison_id: str,
    reports: tuple[tuple[str, Phase1Report, Path], ...],
) -> RuntimeComparisonReport:
    """Build a comparison report from completed per-runtime reports."""
    if not reports:
        msg = "comparison requires at least one runtime report"
        raise ValueError(msg)
    first_report = reports[0][1]
    rows = tuple(_row(runtime, report, path) for runtime, report, path in reports)
    return RuntimeComparisonReport(
        schema_version=1,
        comparison_id=comparison_id,
        model_name=first_report.workload.model.name,
        workload_id=first_report.workload.workload_id,
        energy_basis="mock-dual-telemetry",
        energy_note=MOCK_ENERGY_NOTE,
        measurement_protocol=MEASUREMENT_PROTOCOL,
        rows=rows,
        environment=first_report.environment.to_dict(),
    )


def write_comparison_report(report: RuntimeComparisonReport, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and markdown comparison reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "phase1-host-runtime-comparison.json"
    md_path = output_dir / "phase1-host-runtime-comparison.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_comparison_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_comparison_markdown(report: RuntimeComparisonReport) -> str:
    """Render a concise markdown comparison."""
    lines = [
        "# Phase 1 Host Runtime Comparison",
        "",
        f"- Comparison ID: `{report.comparison_id}`",
        f"- Model: `{report.model_name}`",
        f"- Workload: `{report.workload_id}`",
        f"- Energy basis: `{report.energy_basis}`",
        f"- Energy note: {report.energy_note}",
        f"- Measurement protocol: {report.measurement_protocol}",
        "",
        "## Runtime Metrics",
        "",
        "| Runtime | Backend | tok/s | TTFT ms | Peak MB | Accuracy | Mock J/token | Cross-check |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.rows:
        lines.append(
            f"| `{row.runtime}` | `{row.backend}` | "
            f"{row.mean_tokens_per_second:.3f} | {_fmt(row.median_first_token_ms)} | "
            f"{_fmt(row.peak_memory_mb)} | "
            f"{row.accuracy_score:.3f} ({row.accuracy_passed}/{row.accuracy_total}) | "
            f"{_fmt(row.mock_joules_per_token, precision=6)} | `{row.cross_check_reason}` |",
        )
    lines.extend(["", "## Runtime Pins", ""])
    for row in report.rows:
        lines.append(f"- `{row.runtime}`: `{_first_line(row.version)}`")
        lines.append(f"  - Model revision: `{row.model_revision}`")
        lines.append(f"  - Quantization: `{row.quantization}`")
        lines.append(f"  - Per-runtime report: `{row.report_path}`")
        if row.execution_note:
            lines.append(f"  - Note: {row.execution_note}")
    if len(report.rows) > 1:
        speeds = [row.mean_tokens_per_second for row in report.rows]
        lines.extend(
            [
                "",
                "## Summary",
                "",
                f"- Runtime count: `{len(report.rows)}`",
                f"- tok/s range: `{min(speeds):.3f}` to `{max(speeds):.3f}`",
                f"- tok/s mean: `{statistics.fmean(speeds):.3f}`",
            ],
        )
    return "\n".join(lines).rstrip() + "\n"


def _row(runtime: str, report: Phase1Report, path: Path) -> RuntimeComparisonRow:
    summary = summary_metrics(report.results, report.measurement, report.accuracy)
    return RuntimeComparisonRow(
        runtime=runtime,
        backend=report.runtime.backend,
        version=report.runtime.runtime_version,
        model_name=report.runtime.model_name,
        model_revision=report.runtime.model_revision,
        quantization=report.runtime.quantization,
        mean_tokens_per_second=float(summary["mean_tokens_per_second"]),
        median_first_token_ms=summary["median_first_token_ms"],
        peak_memory_mb=summary["peak_memory_mb"],
        accuracy_score=report.accuracy.score,
        accuracy_passed=report.accuracy.passed,
        accuracy_total=report.accuracy.total,
        mock_joules_per_token=summary["joules_per_token"],
        cross_check_reason=report.measurement.cross_check.reason,
        report_path=str(path),
        execution_note=report.runtime.extra.get("execution_note"),
    )


def _fmt(value: float | None, *, precision: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{precision}f}"


def _first_line(value: str) -> str:
    return value.splitlines()[0] if value else ""
