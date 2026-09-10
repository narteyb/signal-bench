# SPDX-License-Identifier: Apache-2.0
"""Phase 1 report emission."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self

from signal_bench.phase1.accuracy import AccuracySummary
from signal_bench.phase1.environment import EnvironmentManifest
from signal_bench.phase1.measurement import MeasurementSummary
from signal_bench.phase1.runtime import GenerationResult, RuntimeMetadata
from signal_bench.phase1.workload import Phase1Workload


@dataclass(frozen=True, slots=True)
class Phase1Report:
    """Structured Phase 1 host-slice report."""

    schema_version: int
    run_id: str
    workload: Phase1Workload
    runtime: RuntimeMetadata
    results: tuple[GenerationResult, ...]
    accuracy: AccuracySummary
    measurement: MeasurementSummary
    environment: EnvironmentManifest
    hardware_seams: tuple[str, ...]

    def to_dict(self: Self) -> dict[str, Any]:
        """Return JSON-serializable report data."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "workload": asdict(self.workload),
            "runtime": asdict(self.runtime),
            "results": [_generation_to_dict(result) for result in self.results],
            "summary": summary_metrics(self.results, self.measurement, self.accuracy),
            "accuracy": asdict(self.accuracy),
            "measurement": asdict(self.measurement),
            "environment": self.environment.to_dict(),
            "hardware_seams": list(self.hardware_seams),
        }


def summary_metrics(
    results: tuple[GenerationResult, ...],
    measurement: MeasurementSummary,
    accuracy: AccuracySummary,
) -> dict[str, Any]:
    """Return report headline metrics."""
    tokens_per_second = [result.tokens_per_second for result in results]
    first_token_ms = [result.first_token_ms for result in results]
    peak_memory = [result.peak_memory_mb for result in results if result.peak_memory_mb is not None]
    energy = measurement.energy
    return {
        "prompt_count": len(results),
        "total_tokens_out": measurement.total_tokens_out,
        "mean_tokens_per_second": statistics.fmean(tokens_per_second) if tokens_per_second else 0.0,
        "median_first_token_ms": statistics.median(first_token_ms) if first_token_ms else None,
        "peak_memory_mb": max(peak_memory) if peak_memory else None,
        "joules_per_token": energy.joules_per_token if energy is not None else None,
        "avg_power_w": energy.avg_power_w if energy is not None else None,
        "accuracy_score": accuracy.score,
        "accuracy_metric": accuracy.metric,
        "cross_check_flagged": measurement.cross_check.flagged,
    }


def write_report(report: Phase1Report, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and markdown reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "phase1-host-slice-report.json"
    md_path = output_dir / "phase1-host-slice-report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: Phase1Report) -> str:
    """Render a concise markdown report."""
    summary = summary_metrics(report.results, report.measurement, report.accuracy)
    energy = report.measurement.energy
    lines = [
        "# Phase 1 Host Slice Report",
        "",
        f"- Run ID: `{report.run_id}`",
        f"- Model: `{report.runtime.model_name}`",
        f"- Model revision: `{report.runtime.model_revision}`",
        f"- Quantization: `{report.runtime.quantization}`",
        f"- Runtime: `{report.runtime.runtime_name}` `{report.runtime.runtime_version}`",
        f"- Target: `{report.runtime.target_name}` / `{report.runtime.backend}`",
        "",
        "## Headline Metrics",
        "",
        f"- Mean tokens/s: `{summary['mean_tokens_per_second']:.3f}`",
        f"- Median first-token ms: `{summary['median_first_token_ms']:.3f}`",
        f"- Peak memory MB: `{summary['peak_memory_mb']:.3f}`",
        f"- Accuracy: `{report.accuracy.score:.3f}` "
        f"({report.accuracy.passed}/{report.accuracy.total}, {report.accuracy.metric})",
    ]
    if energy is None:
        lines.append("- Joules/token: `unavailable`")
    else:
        lines.extend(
            [
                f"- Joules/token: `{energy.joules_per_token:.6f}`",
                f"- Integrated energy J: `{energy.total_j:.6f}`",
                f"- Average power W: `{energy.avg_power_w:.6f}`",
                f"- Telemetry coverage: `{energy.telemetry_coverage:.3f}`",
            ],
        )
    cc = report.measurement.cross_check
    lines.extend(
        [
            f"- Dual-meter cross-check: `{cc.reason}`",
            "",
            "## Prompt Results",
            "",
            "| Prompt | Duration ms | TTFT ms | Tokens out | tok/s | Pass |",
            "|---|---:|---:|---:|---:|---|",
        ],
    )
    scores = {score.prompt_id: score for score in report.accuracy.prompt_scores}
    for result in report.results:
        lines.append(
            f"| `{result.prompt_id}` | {result.duration_ms:.2f} | "
            f"{result.first_token_ms:.2f} | {result.tokens_out} | "
            f"{result.tokens_per_second:.2f} | {scores[result.prompt_id].passed} |",
        )
    lines.extend(["", "## Environment Pins", ""])
    for name, value in sorted(report.environment.commands.items()):
        lines.append(f"- `{name}`: `{_first_line(value)}`")
    lines.extend(["", "## Hardware Seams", ""])
    lines.extend(f"- {seam}" for seam in report.hardware_seams)
    return "\n".join(lines).rstrip() + "\n"


def _generation_to_dict(result: GenerationResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["started_at"] = result.started_at.isoformat()
    payload["finished_at"] = result.finished_at.isoformat()
    payload["tokens_per_second"] = result.tokens_per_second
    return payload


def _first_line(value: str) -> str:
    return value.splitlines()[0] if value else ""
