# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pytest

from signal_bench.phase1.harness import Phase1Harness, Phase1RunConfig
from signal_bench.phase1.runtime import (
    GenerationRequest,
    GenerationResult,
    RuntimeAdapter,
    RuntimeMetadata,
)
from signal_bench.phase1.telemetry import SyntheticPowerConfig, SyntheticPowerSource
from signal_bench.phase1.workload import default_workload


class _FakeRuntime(RuntimeAdapter):
    def metadata(self) -> RuntimeMetadata:
        return RuntimeMetadata(
            runtime_name="fake-runtime",
            runtime_version="test",
            target_name="m1-max-64gb",
            backend="host-test",
            model_name="fake-model",
            model_revision="test-revision",
            quantization="Q4_TEST",
            model_bytes=1024,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        started_at = dt.datetime.now(dt.UTC)
        time.sleep(0.04)
        finished_at = dt.datetime.now(dt.UTC)
        answers = {
            "eiffel-year": "1889",
            "apollo-landing": "Apollo 11",
            "water-symbol": "H2O",
        }
        return GenerationResult(
            prompt_id=request.prompt_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=(finished_at - started_at).total_seconds() * 1000.0,
            first_token_ms=2.0,
            tokens_in=8,
            tokens_out=4,
            text=answers[request.prompt_id],
            peak_memory_mb=64.0,
        )

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_phase1_harness_emits_report_with_mock_dual_meter(tmp_path: Path) -> None:
    sources = (
        SyntheticPowerSource(
            SyntheticPowerConfig(name="mock_wall_fnb58", sample_rate_hz=100.0, base_power_w=10.0),
        ),
        SyntheticPowerSource(
            SyntheticPowerConfig(name="mock_rail_ina219", sample_rate_hz=100.0, base_power_w=9.8),
        ),
    )
    harness = Phase1Harness(
        Phase1RunConfig(repo_root=Path.cwd(), output_dir=tmp_path),
        runtime_adapter=_FakeRuntime(),
        telemetry_sources=sources,
        workload=default_workload("fake-model"),
    )

    report = await harness.run_async()

    assert report.accuracy.score == 1.0
    assert report.measurement.energy is not None
    assert report.measurement.energy.joules_per_token > 0
    assert report.measurement.cross_check.flagged is False
    assert (tmp_path / "phase1-host-slice-report.json").exists()
    assert (tmp_path / "phase1-host-slice-report.md").exists()
    assert (tmp_path / "environment-manifest.json").exists()
