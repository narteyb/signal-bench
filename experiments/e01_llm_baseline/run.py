# SPDX-License-Identifier: Apache-2.0
"""Orchestrate Experiment 01 measurements."""

from __future__ import annotations

import argparse
import platform
import shutil
import time
from pathlib import Path
from typing import Literal

from experiments.e01_llm_baseline.analysis import render_outputs
from experiments.e01_llm_baseline.prompts import PROMPT_TIERS, PromptTier
from experiments.lib.measurement import InferenceMeasurement, ThermalSampler
from experiments.lib.modal_client import ModalClient
from experiments.lib.ollama_client import OllamaClient, ollama_version
from experiments.lib.schema_writer import ExperimentWriter, TargetSpec

MODEL_TAG = "nemotron-3-nano:4b"
EXPERIMENT_ID = "e01_llm_baseline"
CONFIG_PATH = Path("experiments/configs/llm-baseline-nemoclaw.yaml")
WARMUP_COUNT = 5
MEASUREMENT_COUNT = 20
TEMPERATURE = 0.0
TOP_P = 1.0
SEED = 42
NUM_CTX = 4096


def main() -> None:
    """Run Experiment 01."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("signal-bench.db"))
    parser.add_argument("--model", default=MODEL_TAG)
    parser.add_argument("--targets", choices=["mac", "modal", "both"], default="both")
    parser.add_argument(
        "--tiers", nargs="+", choices=sorted(PROMPT_TIERS), default=list(PROMPT_TIERS)
    )
    parser.add_argument("--skip-thermal", action="store_true")
    parser.add_argument("--thermal-duration-s", type=int, default=480)
    args = parser.parse_args()

    writer = ExperimentWriter(args.db)
    writer.migrate()
    task = writer.upsert_task(CONFIG_PATH)

    model = str(args.model)
    mac_info = (
        run_mac_protocol(writer, task.task_id, model, args.tiers)
        if args.targets in {"mac", "both"}
        else None
    )

    if args.targets in {"modal", "both"}:
        if mac_info is None:
            mac_info = local_model_info(model)
        run_modal_protocol(
            writer, task.task_id, model, args.tiers, expected_hash=mac_info["digest"]
        )

    if not args.skip_thermal and args.targets in {"mac", "both"}:
        run_thermal_protocol(writer, task.task_id, model, duration_s=args.thermal_duration_s)

    result_path = render_outputs(args.db, Path("experiments/results"), Path("docs"))
    print(f"wrote {result_path}")


def run_mac_protocol(
    writer: ExperimentWriter,
    task_id: str,
    model: str,
    tiers: list[str],
) -> dict[str, str | None]:
    """Run the N=20+5 protocol locally through Ollama."""
    client = OllamaClient()
    info = client.require_model(model)
    target = writer.upsert_target(mac_target_spec(), model_hash=info.digest)
    for tier_name in tiers:
        tier = PROMPT_TIERS[tier_name]
        print(f"mac/{tier.name}: warming {WARMUP_COUNT}, measuring {MEASUREMENT_COUNT}")
        for _ in range(WARMUP_COUNT):
            client.generate(
                model=model,
                prompt=tier.prompt,
                max_tokens=tier.max_tokens,
                seed=SEED,
                temperature=TEMPERATURE,
                top_p=TOP_P,
            )
        measurements = [mac_measurement(client, model, tier) for _ in range(MEASUREMENT_COUNT)]
        run = writer.create_run(
            target_id=target.target_id,
            task_id=task_id,
            warmup_count=WARMUP_COUNT,
            measurement_count=MEASUREMENT_COUNT,
            runtime_name="ollama",
            runtime_version=ollama_version(),
            model_name=model,
            model_hash=info.digest,
            quantization=info.quantization,
            notes="Experiment 01 Mac local protocol run.",
            extra={
                "experiment_id": EXPERIMENT_ID,
                "run_kind": "protocol",
                "prompt_tier": tier.name,
                "generation": generation_settings(),
            },
        )
        writer.add_results(run.run_id, measurements)
        writer.complete_run(run.run_id)
    return {"digest": info.digest, "quantization": info.quantization}


def run_modal_protocol(
    writer: ExperimentWriter,
    task_id: str,
    model: str,
    tiers: list[str],
    *,
    expected_hash: str,
) -> None:
    """Run the N=20+5 protocol on Modal A10G."""
    client = ModalClient()
    modal_target = writer.upsert_target(
        TargetSpec(
            name="modal-a10g",
            kind="modal",
            cpu="N/A (cloud)",
            accelerator="NVIDIA A10G (24GB)",
            ram_mb=49152,
            storage_mb=100_000,
            os_name="Linux (Modal container)",
            os_version=None,
            extra={"modal_app": "signal-bench-e01-llm", "instance_type": "A10G"},
        ),
    )
    for tier_name in tiers:
        tier = PROMPT_TIERS[tier_name]
        print(f"modal/{tier.name}: remote protocol")
        model_info, os_version, measurements = client.run_protocol(
            model=model,
            prompt=tier.prompt,
            max_tokens=tier.max_tokens,
            seed=SEED,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            warmup_count=WARMUP_COUNT,
            measurement_count=MEASUREMENT_COUNT,
        )
        digest = str(model_info["digest"])
        if digest != expected_hash:
            raise RuntimeError(f"Modal digest {digest} did not match Mac digest {expected_hash}")
        modal_target.os_version = os_version
        modal_target = writer.upsert_target(
            TargetSpec(
                name="modal-a10g",
                kind="modal",
                cpu="N/A (cloud)",
                accelerator="NVIDIA A10G (24GB)",
                ram_mb=49152,
                storage_mb=100_000,
                os_name="Linux (Modal container)",
                os_version=os_version,
                extra={"modal_app": "signal-bench-e01-llm", "instance_type": "A10G"},
            ),
            model_hash=digest,
        )
        details = model_info.get("details") or {}
        run = writer.create_run(
            target_id=modal_target.target_id,
            task_id=task_id,
            warmup_count=WARMUP_COUNT,
            measurement_count=MEASUREMENT_COUNT,
            runtime_name="ollama",
            runtime_version="modal container ollama",
            model_name=model,
            model_hash=digest,
            quantization=details.get("quantization_level"),
            notes="Experiment 01 Modal A10G protocol run.",
            extra={
                "experiment_id": EXPERIMENT_ID,
                "run_kind": "protocol",
                "prompt_tier": tier.name,
                "generation": generation_settings(),
            },
        )
        writer.add_results(run.run_id, measurements)
        writer.complete_run(run.run_id)


def run_thermal_protocol(
    writer: ExperimentWriter,
    task_id: str,
    model: str,
    *,
    duration_s: int,
) -> None:
    """Run sustained medium-tier inference on the Mac and record thermal snapshots."""
    client = OllamaClient()
    info = client.require_model(model)
    target = writer.upsert_target(mac_target_spec(), model_hash=info.digest)
    run = writer.create_run(
        target_id=target.target_id,
        task_id=task_id,
        warmup_count=0,
        measurement_count=0,
        runtime_name="ollama",
        runtime_version=ollama_version(),
        model_name=model,
        model_hash=info.digest,
        quantization=info.quantization,
        notes="Experiment 01 sustained M1 Max thermal stability run.",
        extra={
            "experiment_id": EXPERIMENT_ID,
            "run_kind": "thermal",
            "prompt_tier": "medium",
            "duration_s": duration_s,
            "generation": generation_settings(),
        },
    )
    sampler = ThermalSampler(interval_s=10.0)
    sampler.start()
    measurements: list[InferenceMeasurement] = []
    deadline = time.monotonic() + duration_s
    print(f"mac/thermal: running for {duration_s}s")
    try:
        while time.monotonic() < deadline:
            measurements.append(mac_measurement(client, model, PROMPT_TIERS["medium"]))
    finally:
        thermal_samples = [
            {
                "timestamp": sample.timestamp.isoformat(),
                "thermal_state": sample.thermal_state,
                "raw": sample.raw,
            }
            for sample in sampler.stop()
        ]
    writer.add_results(run.run_id, measurements)
    writer.complete_run(
        run.run_id,
        {
            "thermal_samples": thermal_samples,
            "measurement_count_actual": len(measurements),
        },
    )


def mac_measurement(client: OllamaClient, model: str, tier: PromptTier) -> InferenceMeasurement:
    """Capture one local Ollama measurement and annotate Mac-specific extras."""
    measurement = client.generate(
        model=model,
        prompt=tier.prompt,
        max_tokens=tier.max_tokens,
        seed=SEED,
        temperature=TEMPERATURE,
        top_p=TOP_P,
    )
    extra = dict(measurement.extra)
    extra["thermal_pressure"] = None
    extra["prompt_tier"] = tier.name
    return InferenceMeasurement(
        started_at=measurement.started_at,
        duration_ms=measurement.duration_ms,
        first_token_ms=measurement.first_token_ms,
        tokens_in=measurement.tokens_in,
        tokens_out=measurement.tokens_out,
        throughput_value=measurement.throughput_value,
        completion=measurement.completion,
        extra=extra,
    )


def local_model_info(model: str) -> dict[str, str | None]:
    """Return digest information for the local model."""
    info = OllamaClient().require_model(model)
    return {"digest": info.digest, "quantization": info.quantization}


def mac_target_spec() -> TargetSpec:
    """Build the local Mac target metadata."""
    disk = shutil.disk_usage("/")
    return TargetSpec(
        name="m1-max-64gb",
        kind="local",
        cpu="Apple M1 Max (10-core)",
        accelerator="Apple Neural Engine + Metal GPU",
        ram_mb=65536,
        storage_mb=disk.total // (1024 * 1024),
        os_name="macOS",
        os_version=f"{platform.mac_ver()[0]} ({platform.release()})",
        extra={"ollama_version": ollama_version(), "metal_supported": True},
    )


def generation_settings() -> dict[str, float | int]:
    """Return generation settings recorded on each run."""
    return {"temperature": TEMPERATURE, "top_p": TOP_P, "seed": SEED, "num_ctx": NUM_CTX}


TargetChoice = Literal["mac", "modal", "both"]
