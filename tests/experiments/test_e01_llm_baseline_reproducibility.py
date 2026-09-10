# SPDX-License-Identifier: Apache-2.0
"""Reproducibility tests for Experiment 01 recorded fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import respx

from experiments.e01_llm_baseline.analysis import summarize_experiment
from experiments.e01_llm_baseline.run import EXPERIMENT_ID, generation_settings
from experiments.lib.measurement import InferenceMeasurement
from experiments.lib.schema_writer import ExperimentWriter, TargetSpec

FIXTURE_DIR = Path("tests/experiments/fixtures/e01")
FIXTURE_URL = "https://fixtures.signal-bench.local/e01/protocol_summary.json"

EXPECTED = {
    ("m1-max-64gb", "short"): {"p50_ms": 1286.0, "p99_ms": 1494.9, "mean_tok_s": 37.72},
    ("m1-max-64gb", "medium"): {"p50_ms": 3527.5, "p99_ms": 4254.8, "mean_tok_s": 39.97},
    ("m1-max-64gb", "long"): {"p50_ms": 5063.2, "p99_ms": 6299.1, "mean_tok_s": 30.44},
    ("modal-a10g", "short"): {"p50_ms": 676.8, "p99_ms": 689.2, "mean_tok_s": 73.83},
    ("modal-a10g", "medium"): {"p50_ms": 1444.6, "p99_ms": 1551.0, "mean_tok_s": 103.24},
    ("modal-a10g", "long"): {"p50_ms": 1647.5, "p99_ms": 1657.1, "mean_tok_s": 97.16},
}


@respx.mock
def test_e01_reproducibility_within_inv12_bounds(tmp_path: Path) -> None:
    """Replay recorded Modal and Ollama fixture data and assert frozen E01 numbers."""
    fixture = json.loads((FIXTURE_DIR / "protocol_summary.json").read_text(encoding="utf-8"))
    fixture_route = respx.get(FIXTURE_URL).mock(return_value=httpx.Response(200, json=fixture))
    replayed = httpx.get(FIXTURE_URL).json()

    db_path = tmp_path / "e01-repro.db"
    writer = ExperimentWriter(db_path)
    writer.migrate()
    task = writer.upsert_task(Path("experiments/configs/llm-baseline-nemoclaw.yaml"))
    _write_recorded_runs(writer, task.task_id, replayed)

    actual = {
        (row["target"], row["tier"]): row
        for row in summarize_experiment(db_path, experiment_id=EXPERIMENT_ID)
    }

    assert set(actual) == set(EXPECTED)
    for key, expected in EXPECTED.items():
        row = actual[key]
        assert relative_delta(row["p50_ms"], expected["p50_ms"]) < 0.05
        assert relative_delta(row["mean_tok_s"], expected["mean_tok_s"]) < 0.05
        expected_ratio = expected["p99_ms"] / expected["p50_ms"]
        actual_ratio = row["p99_ms"] / row["p50_ms"]
        assert abs(actual_ratio - expected_ratio) < 0.05
        assert row["count"] == 20

    assert fixture_route.called


def _write_recorded_runs(writer: ExperimentWriter, task_id: str, fixture: dict[str, Any]) -> None:
    model = fixture["model"]
    for target_name, target_fixture in fixture["targets"].items():
        target = writer.upsert_target(
            TargetSpec(
                name=target_name,
                kind=target_fixture["kind"],
                cpu=target_fixture["cpu"],
                accelerator=target_fixture["accelerator"],
                ram_mb=target_fixture["ram_mb"],
                storage_mb=target_fixture["storage_mb"],
                os_name=target_fixture["os_name"],
                os_version=target_fixture["os_version"],
                extra=target_fixture["extra"],
            ),
            model_hash=model["hash"],
        )
        for tier, stats in fixture["runs"][target_name].items():
            run = writer.create_run(
                target_id=target.target_id,
                task_id=task_id,
                warmup_count=5,
                measurement_count=20,
                runtime_name="ollama",
                runtime_version=target_fixture["runtime_version"],
                model_name=model["name"],
                model_hash=model["hash"],
                quantization=model["quantization"],
                notes="Experiment 01 recorded fixture replay.",
                extra={
                    "experiment_id": EXPERIMENT_ID,
                    "run_kind": "protocol",
                    "prompt_tier": tier,
                    "generation": generation_settings(),
                },
            )
            writer.add_results(run.run_id, recorded_measurements(target_name, tier, stats))
            writer.complete_run(run.run_id)


def recorded_measurements(
    target_name: str,
    tier: str,
    stats: dict[str, float | int],
) -> list[InferenceMeasurement]:
    """Return 20 sorted measurements whose percentiles match the recorded E01 summary."""
    p50 = float(stats["p50_ms"])
    p95 = float(stats["p95_ms"])
    p99 = float(stats["p99_ms"])
    durations = [p50 * 0.9 for _ in range(9)]
    durations.extend([p50])
    durations.extend([((p50 + p95) / 2.0) for _ in range(8)])
    durations.extend([p95, p99])
    started = datetime(2026, 5, 3, 9, 0, tzinfo=UTC)
    return [
        InferenceMeasurement(
            started_at=started + timedelta(seconds=index),
            duration_ms=duration,
            first_token_ms=duration * 0.25,
            tokens_in=int(stats["tokens_in"]),
            tokens_out=int(stats["tokens_out"]),
            throughput_value=float(stats["mean_tok_s"]),
            completion=f"recorded {target_name} {tier} completion {index}",
            extra={
                "fixture": "e01",
                "target": target_name,
                "tier": tier,
                "billing_seconds": duration / 1000.0 if target_name == "modal-a10g" else 0.0,
            },
        )
        for index, duration in enumerate(durations, start=1)
    ]


def relative_delta(actual: float, expected: float) -> float:
    """Return relative absolute delta."""
    return abs(actual - expected) / expected
