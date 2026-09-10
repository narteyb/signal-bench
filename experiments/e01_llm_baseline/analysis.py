# SPDX-License-Identifier: Apache-2.0
"""Analyze Experiment 01 database rows and render Markdown outputs."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import select

from experiments.lib.schema_writer import make_engine, session_factory_for
from signal_bench.schema import Result, Run, Target

MODAL_A10_PRICE_PER_SECOND_USD = 0.000306


def percentile(values: list[float], pct: float) -> float:
    """Return nearest-rank percentile for small benchmark samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return ordered[index]


def summarize_experiment(
    db_path: Path, *, experiment_id: str = "e01_llm_baseline"
) -> list[dict[str, Any]]:
    """Compute per-run statistics for Experiment 01."""
    engine = make_engine(db_path)
    SessionLocal = session_factory_for(engine)
    rows: list[dict[str, Any]] = []
    with SessionLocal() as session:
        runs = session.scalars(
            select(Run)
            .join(Target)
            .where(Run.extra["experiment_id"].as_string() == experiment_id)
            .where(Run.extra["run_kind"].as_string() == "protocol")
            .order_by(Target.name, Run.extra["prompt_tier"].as_string()),
        ).all()
        for run in runs:
            target = session.get(Target, run.target_id)
            results = session.scalars(
                select(Result).where(Result.run_id == run.run_id).order_by(Result.sequence),
            ).all()
            durations = [float(result.duration_ms) for result in results]
            throughputs = [float(result.throughput_value or 0.0) for result in results]
            p50 = percentile(durations, 50)
            p95 = percentile(durations, 95)
            p99 = percentile(durations, 99)
            avg = mean(durations) if durations else 0.0
            rows.append(
                {
                    "run_id": run.run_id,
                    "target": target.name if target else run.target_id,
                    "tier": (run.extra or {}).get("prompt_tier"),
                    "count": len(results),
                    "p50_ms": p50,
                    "p95_ms": p95,
                    "p99_ms": p99,
                    "p99_p50": p99 / p50 if p50 else 0.0,
                    "cv": pstdev(durations) / avg if len(durations) > 1 and avg else 0.0,
                    "mean_tok_s": mean(throughputs) if throughputs else 0.0,
                    "model_hash": run.model_hash,
                },
            )
    return rows


def thermal_summary(
    db_path: Path, *, experiment_id: str = "e01_llm_baseline"
) -> dict[str, Any] | None:
    """Return the sustained thermal run summary if present."""
    engine = make_engine(db_path)
    SessionLocal = session_factory_for(engine)
    with SessionLocal() as session:
        run = session.scalar(
            select(Run)
            .where(Run.extra["experiment_id"].as_string() == experiment_id)
            .where(Run.extra["run_kind"].as_string() == "thermal")
            .order_by(Run.started_at.desc()),
        )
        if run is None:
            return None
        results = session.scalars(select(Result).where(Result.run_id == run.run_id)).all()
        durations = [float(result.duration_ms) for result in results]
        extra = dict(run.extra or {})
        samples = extra.get("thermal_samples") or []
        first_half = durations[: max(1, len(durations) // 2)]
        second_half = durations[max(1, len(durations) // 2) :]
        return {
            "run_id": run.run_id,
            "count": len(results),
            "samples": samples,
            "first_half_mean_ms": mean(first_half) if first_half else 0.0,
            "second_half_mean_ms": mean(second_half) if second_half else 0.0,
            "degradation_pct": (
                ((mean(second_half) - mean(first_half)) / mean(first_half)) * 100.0
                if first_half and second_half and mean(first_half)
                else 0.0
            ),
        }


def render_outputs(db_path: Path, output_dir: Path, docs_dir: Path) -> Path:
    """Render experiment findings and the draft methodology doc."""
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    summaries = summarize_experiment(db_path)
    thermal = thermal_summary(db_path)
    result_path = output_dir / f"{date.today().isoformat()}-llm-baseline-mac-modal.md"
    result_path.write_text(render_results_markdown(summaries, thermal, db_path), encoding="utf-8")
    (docs_dir / "methodology.md").write_text(
        render_methodology_markdown(summaries, thermal),
        encoding="utf-8",
    )
    return result_path


def render_results_markdown(
    summaries: list[dict[str, Any]],
    thermal: dict[str, Any] | None,
    db_path: Path,
) -> str:
    """Render the Experiment 01 findings summary."""
    lines = [
        "# Experiment 01: M1 Max + Modal A10G LLM Baseline",
        "",
        "Protocol: 5 warmups + 20 persisted measurements per target/tier. Generation uses "
        "`temperature=0.0`, `top_p=1.0`, and `seed=42`.",
        "",
        "## Latency And Throughput",
        "",
        "| Target | Tier | N | p50 ms | p95 ms | p99 ms | p99/p50 | CV | Mean tok/s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {target} | {tier} | {count} | {p50_ms:.1f} | {p95_ms:.1f} | {p99_ms:.1f} | "
            "{p99_p50:.2f} | {cv:.3f} | {mean_tok_s:.2f} |".format(**row),
        )

    failures = [row for row in summaries if row["p99_p50"] >= 1.4]
    lines.extend(
        [
            "",
            "## Methodology Validation",
            "",
            (
                "The p99/p50 < 1.4 target held for all measured combinations."
                if not failures
                else "The p99/p50 < 1.4 target failed for: "
                + ", ".join(f"{row['target']}/{row['tier']}" for row in failures)
                + "."
            ),
            "",
            "## Thermal Stability",
            "",
        ],
    )
    if thermal is None:
        lines.append("No sustained thermal run is present in the database.")
    else:
        lines.append(
            "Sustained run `{run_id}` recorded {count} inferences. Mean duration changed from "
            "{first_half_mean_ms:.1f} ms in the first half to {second_half_mean_ms:.1f} ms in "
            "the second half ({degradation_pct:.1f}% change).".format(**thermal),
        )
        lines.append(f"Thermal snapshots captured: {len(thermal['samples'])}.")
        if thermal_state_unavailable(thermal):
            lines.append(
                "Direct macOS thermal-state readings were unavailable on this host; the raw "
                "sysctl error is stored with each thermal snapshot."
            )

    modal_billing_seconds = _modal_billing_seconds(db_path)
    lines.extend(
        [
            "",
            "## Modal Cost",
            "",
            "Modal A10 price source: [official Modal pricing page](https://modal.com/pricing), "
            f"${MODAL_A10_PRICE_PER_SECOND_USD:.6f}/sec.",
            f"Recorded billing seconds: {modal_billing_seconds:.2f}.",
            f"Estimated GPU cost: ${modal_billing_seconds * MODAL_A10_PRICE_PER_SECOND_USD:.4f}.",
            "",
            "## Deviations",
            "",
            "Completion caps were reduced after the first full local long-tier attempt stalled for "
            "more than five minutes. The N=20+5 protocol, three prompt-length tiers, fixed seed, "
            "and cross-target model digest assertion remained unchanged.",
            "",
        ],
    )
    return "\n".join(lines)


def render_methodology_markdown(
    summaries: list[dict[str, Any]],
    thermal: dict[str, Any] | None,
) -> str:
    """Render the draft methodology document."""
    lines = [
        "# signal-bench Methodology",
        "",
        "Draft created from Experiment 01. The M5 methodology doc will expand this into the "
        "public release version.",
        "",
        "## Why N=20+5",
        "",
        "Each run performs five warmup inferences that are discarded, then persists twenty "
        "measurements. The warmup phase absorbs model loading and early cache effects; the "
        "measurement phase is small enough to run on constrained devices but large enough to "
        "report p50, p95, p99, coefficient of variation, and p99/p50 consistency.",
        "",
        "## Determinism",
        "",
        "LLM runs use `temperature=0.0`, `top_p=1.0`, and `seed=42`. Experiment 01 records "
        "the resolved Ollama model digest in `runs.model_hash` and asserts the Modal digest "
        "matches the Mac digest before Modal results are accepted.",
        "",
        "## Statistical Bounds Observed",
        "",
        "| Target | Tier | p50 ms | p95 ms | p99 ms | p99/p50 | CV |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {target} | {tier} | {p50_ms:.1f} | {p95_ms:.1f} | {p99_ms:.1f} | "
            "{p99_p50:.2f} | {cv:.3f} |".format(**row),
        )
    lines.extend(["", "## Thermal Observations", ""])
    if thermal is None:
        lines.append("The sustained M1 Max thermal run has not been recorded yet.")
    else:
        lines.append(
            "The sustained M1 Max medium-tier run recorded {count} inferences. Mean duration "
            "changed by {degradation_pct:.1f}% between the first and second halves. Thermal "
            "state samples are stored in the Run `extra` JSON.".format(**thermal),
        )
        if thermal_state_unavailable(thermal):
            lines.append(
                "On this Mac, `machdep.xcpm.cpu_thermal_state` was unavailable, so Experiment 01 "
                "uses latency drift as the practical thermal-stability signal and keeps the raw "
                "sysctl errors for follow-up."
            )
    lines.extend(
        [
            "",
            "## Open Questions",
            "",
            "- Confirm whether constrained devices need more than five warmups when model load and "
            "allocator behavior dominate early measurements.",
            "- Preserve exact model digests whenever a provider exposes them; plain model names are "
            "not enough for cross-target comparisons.",
            "- Decide how the M4 telemetry join should handle LLM runs with long first-token latency "
            "and bursty decode phases.",
            "",
        ],
    )
    return "\n".join(lines)


def _modal_billing_seconds(db_path: Path = Path("signal-bench.db")) -> float:
    totals: defaultdict[str, float] = defaultdict(float)
    engine = make_engine(db_path)
    SessionLocal = session_factory_for(engine)
    with SessionLocal() as session:
        runs = session.scalars(
            select(Run)
            .join(Target)
            .where(Target.name == "modal-a10g")
            .where(Run.extra["experiment_id"].as_string() == "e01_llm_baseline"),
        ).all()
        for run in runs:
            results = session.scalars(select(Result).where(Result.run_id == run.run_id)).all()
            for result in results:
                extra = result.extra or {}
                totals[run.run_id] += float(extra.get("billing_seconds") or 0.0)
    return sum(totals.values())


def thermal_state_unavailable(thermal: dict[str, Any]) -> bool:
    """Return True when every thermal snapshot lacks a parsed state."""
    samples = thermal.get("samples") or []
    return bool(samples) and all(sample.get("thermal_state") is None for sample in samples)
