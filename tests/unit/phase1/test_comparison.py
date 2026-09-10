# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt
from pathlib import Path

from signal_bench.phase1.accuracy import AccuracySummary, PromptScore
from signal_bench.phase1.comparison import build_runtime_comparison, write_comparison_report
from signal_bench.phase1.environment import EnvironmentManifest
from signal_bench.phase1.measurement import CrossCheckResult, EnergySummary, MeasurementSummary
from signal_bench.phase1.report import Phase1Report
from signal_bench.phase1.runtime import GenerationResult, RuntimeMetadata
from signal_bench.phase1.workload import default_workload


def _report(runtime: str) -> Phase1Report:
    now = dt.datetime.now(dt.UTC)
    return Phase1Report(
        schema_version=1,
        run_id=f"run-{runtime}",
        workload=default_workload("qwen2.5:7b"),
        runtime=RuntimeMetadata(
            runtime_name=runtime,
            runtime_version="test-version",
            target_name="m1-max-64gb",
            backend=f"{runtime}-backend",
            model_name="qwen2.5:7b",
            model_revision="test-revision",
            quantization="Q4_K_M",
        ),
        results=(
            GenerationResult(
                prompt_id="eiffel-year",
                started_at=now,
                finished_at=now,
                duration_ms=100.0,
                first_token_ms=10.0,
                tokens_in=8,
                tokens_out=4,
                text="1889",
                peak_memory_mb=32.0,
            ),
        ),
        accuracy=AccuracySummary(
            metric="deterministic_contains_all",
            score=1.0,
            passed=1,
            total=1,
            prompt_scores=(
                PromptScore(
                    prompt_id="eiffel-year",
                    passed=True,
                    score=1.0,
                    expected=("1889",),
                    observed="1889",
                ),
            ),
        ),
        measurement=MeasurementSummary(
            primary_source="mock_wall_fnb58",
            total_tokens_out=4,
            run_duration_s=1.0,
            energy=EnergySummary(
                source="mock_wall_fnb58",
                metric="power",
                sample_count=2,
                total_j=2.0,
                avg_power_w=2.0,
                duration_s=1.0,
                joules_per_token=0.5,
                telemetry_coverage=1.0,
            ),
            cross_check=CrossCheckResult(
                compared=True,
                source_a="mock_rail_ina219",
                source_b="mock_wall_fnb58",
                delta_j=0.01,
                relative_delta=0.01,
                threshold=0.10,
                flagged=False,
                reason="ok",
            ),
        ),
        environment=EnvironmentManifest(
            repo_root=Path.cwd(),
            git_sha="test",
            git_dirty=False,
            platform="test",
            python_version="3.12",
            commands={},
            files={},
        ),
        hardware_seams=(),
    )


def test_comparison_report_labels_energy_as_mock(tmp_path: Path) -> None:
    comparison = build_runtime_comparison(
        "comparison-test",
        (
            ("ollama", _report("ollama"), Path("ollama/report.json")),
            ("llama.cpp", _report("llama.cpp"), Path("llama/report.json")),
        ),
    )

    json_path, md_path = write_comparison_report(comparison, tmp_path)

    assert comparison.energy_basis == "mock-dual-telemetry"
    assert "not physical measurements" in comparison.energy_note
    assert "warm_steady_state_v1" in comparison.measurement_protocol
    assert len(comparison.rows) == 2
    assert json_path.exists()
    assert "Mock J/token" in md_path.read_text()
    assert "v02 comparison is superseded" in md_path.read_text()
