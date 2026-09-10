# SPDX-License-Identifier: Apache-2.0
"""Backend-agnostic Phase 1 host-buildable harness."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from signal_bench.ids import new_id
from signal_bench.phase1.accuracy import score_generations
from signal_bench.phase1.adapters import (
    OllamaAdapterConfig,
    OllamaRuntimeAdapter,
    hailo_hef_adapter,
    jetson_tensorrt_llm_adapter,
    pi_llama_cpp_adapter,
)
from signal_bench.phase1.environment import collect_environment, write_environment_manifest
from signal_bench.phase1.measurement import TelemetryRecorder, summarize_measurement
from signal_bench.phase1.report import Phase1Report, write_report
from signal_bench.phase1.runtime import GenerationRequest, RuntimeAdapter
from signal_bench.phase1.telemetry import default_mock_sources
from signal_bench.phase1.workload import Phase1Workload, default_workload
from signal_bench.telemetry.base import TelemetrySource


@dataclass(frozen=True, slots=True)
class Phase1RunConfig:
    """Configuration for one Phase 1 host-slice run."""

    repo_root: Path
    output_dir: Path
    model: str = "qwen2.5:7b"
    runtime: str = "ollama"
    telemetry: str = "mock-dual"
    primary_power_source: str = "mock_wall_fnb58"
    cross_check_sources: tuple[str, str] | None = ("mock_rail_ina219", "mock_wall_fnb58")


class Phase1Harness:
    """Run Phase 1 workloads through backend-neutral interfaces."""

    def __init__(
        self: Self,
        config: Phase1RunConfig,
        *,
        runtime_adapter: RuntimeAdapter | None = None,
        telemetry_sources: tuple[TelemetrySource, ...] | None = None,
        workload: Phase1Workload | None = None,
    ) -> None:
        self._config = config
        self._runtime_adapter = runtime_adapter
        self._telemetry_sources = telemetry_sources
        self._workload = workload

    def run(self: Self) -> Phase1Report:
        """Run the configured Phase 1 host slice."""
        return asyncio.run(self.run_async())

    async def run_async(self: Self) -> Phase1Report:
        """Run the configured Phase 1 host slice asynchronously."""
        workload = self._workload or default_workload(self._config.model)
        runtime = self._runtime_adapter or self._build_runtime()
        sources = self._telemetry_sources or default_mock_sources()
        recorder = TelemetryRecorder(sources)
        run_id = new_id()
        started_at = dt.datetime.now(dt.UTC)
        results = []
        try:
            await recorder.start()
            for prompt in workload.prompts:
                results.append(
                    await asyncio.to_thread(
                        runtime.generate,
                        GenerationRequest(
                            prompt_id=prompt.prompt_id,
                            prompt=prompt.prompt,
                            decode=prompt.decode,
                        ),
                    ),
                )
        finally:
            await recorder.stop()
            runtime.close()
        finished_at = dt.datetime.now(dt.UTC)
        result_tuple = tuple(results)
        accuracy = score_generations(workload.prompts, result_tuple)
        measurement = summarize_measurement(
            recorder.samples,
            result_tuple,
            started_at=started_at,
            finished_at=finished_at,
            primary_source=self._config.primary_power_source,
            cross_check_sources=self._config.cross_check_sources,
        )
        environment = collect_environment(self._config.repo_root)
        report = Phase1Report(
            schema_version=1,
            run_id=run_id,
            workload=workload,
            runtime=runtime.metadata(),
            results=result_tuple,
            accuracy=accuracy,
            measurement=measurement,
            environment=environment,
            hardware_seams=hardware_seams(workload.model.name),
        )
        write_report(report, self._config.output_dir)
        write_environment_manifest(
            environment,
            self._config.output_dir / "environment-manifest.json",
        )
        return report

    def _build_runtime(self: Self) -> RuntimeAdapter:
        if self._config.runtime == "ollama":
            return OllamaRuntimeAdapter(OllamaAdapterConfig(model=self._config.model))
        msg = f"unsupported Phase 1 runtime for host slice: {self._config.runtime}"
        raise ValueError(msg)


def hardware_seams(model_name: str) -> tuple[str, ...]:
    """Return hardware seams represented by non-host adapters."""
    adapters = (
        pi_llama_cpp_adapter(model_name),
        jetson_tensorrt_llm_adapter(model_name),
        hailo_hef_adapter(model_name),
    )
    return tuple(str(adapter.metadata().extra["hardware_seam"]) for adapter in adapters)
