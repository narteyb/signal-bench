# SPDX-License-Identifier: Apache-2.0
"""Frozen Phase 1 host-slice model and prompt workload."""

from __future__ import annotations

from dataclasses import dataclass

from signal_bench.phase1.runtime import DecodeParams


@dataclass(frozen=True, slots=True)
class AccuracyCriterion:
    """Simple deterministic scoring rule for one prompt."""

    kind: str
    expected: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PromptCase:
    """One frozen SLM prompt case."""

    prompt_id: str
    prompt: str
    decode: DecodeParams
    accuracy: AccuracyCriterion
    task_type: str = "accuracy_smoke"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Pinned model selection for the host-buildable slice."""

    name: str
    provider: str
    revision: str
    quantization: str
    license_name: str
    fit_ceiling_gb: int
    format_name: str
    selection_note: str


@dataclass(frozen=True, slots=True)
class Phase1Workload:
    """Pinned model plus frozen prompt/decode suite."""

    workload_id: str
    model: ModelSpec
    prompts: tuple[PromptCase, ...]


def default_workload(model_name: str = "qwen2.5:7b") -> Phase1Workload:
    """Return the default host-buildable Phase 1 SLM workload."""
    model = ModelSpec(
        name=model_name,
        provider="ollama-local",
        revision="resolved-at-runtime-by-ollama-digest",
        quantization="Q4_K_M",
        license_name="Apache-2.0",
        fit_ceiling_gb=8,
        format_name="Ollama quantized model store",
        selection_note=(
            "7.6B parameter Q4_K_M quantized SLM already present on the M1 Max host; "
            "4.7 GB local artifact fits the 8 GB target ceiling and produces visible "
            "deterministic answers for the smoke accuracy suite."
        ),
    )
    decode = DecodeParams(max_tokens=24)
    prompts = (
        PromptCase(
            prompt_id="eiffel-year",
            prompt=(
                "Answer with only the four-digit year. " "What year was the Eiffel Tower completed?"
            ),
            decode=decode,
            accuracy=AccuracyCriterion(kind="contains_all", expected=("1889",)),
        ),
        PromptCase(
            prompt_id="apollo-landing",
            prompt=(
                "Answer with only the mission name. "
                "Which Apollo mission first landed humans on the Moon?"
            ),
            decode=decode,
            accuracy=AccuracyCriterion(kind="contains_all", expected=("apollo", "11")),
        ),
        PromptCase(
            prompt_id="water-symbol",
            prompt="Answer with only the chemical formula for water.",
            decode=decode,
            accuracy=AccuracyCriterion(kind="contains_all", expected=("h2o",)),
        ),
    )
    return Phase1Workload(
        workload_id="phase1-host-slm-smoke-v1",
        model=model,
        prompts=prompts,
    )


def canonical_llm_workload(model_name: str = "qwen2.5:7b") -> Phase1Workload:
    """Return the canonical Phase 1 LLM task suite.

    The suite follows the Signal Reports methodology: one 512-token throughput
    task, one 64-token latency task, and one deterministic classification task.
    """
    model = ModelSpec(
        name=model_name,
        provider="ollama-local",
        revision="resolved-at-runtime-by-ollama-digest",
        quantization="Q4_K_M",
        license_name="Apache-2.0",
        fit_ceiling_gb=8,
        format_name="Ollama quantized model store",
        selection_note=(
            "Q4_K_M quantized SLM artifact available through Ollama on the Pi 5 "
            "and M1 host; selected for the first canonical CPU-target protocol run."
        ),
    )
    prompts = (
        PromptCase(
            prompt_id="throughput-512",
            task_type="throughput",
            prompt=(
                "Write a detailed technical field note about measuring energy "
                "use for edge AI inference on a Raspberry Pi. Cover the purpose "
                "of wall-side power measurement, rail-side measurement, ambient "
                "temperature logging, repeat runs, thermal control, and version "
                "pinning. Continue until the response is long enough for a "
                "512-token generation benchmark."
            ),
            decode=DecodeParams(max_tokens=512),
            accuracy=AccuracyCriterion(kind="contains_all", expected=()),
        ),
        PromptCase(
            prompt_id="latency-64",
            task_type="latency",
            prompt=(
                "In one concise paragraph, explain why edge AI benchmarks must "
                "report both time-to-first-token and energy use."
            ),
            decode=DecodeParams(max_tokens=64),
            accuracy=AccuracyCriterion(kind="contains_all", expected=()),
        ),
        PromptCase(
            prompt_id="classification-edge",
            task_type="classification",
            prompt=(
                "Classify the deployment scenario using exactly one label: EDGE, "
                "CLOUD, or HYBRID. Scenario: a solar-powered camera in a remote "
                "farm must identify crop pests locally because network access is "
                "intermittent. Answer with only the label."
            ),
            decode=DecodeParams(max_tokens=8),
            accuracy=AccuracyCriterion(kind="contains_all", expected=("edge",)),
        ),
    )
    return Phase1Workload(
        workload_id="phase1-canonical-llm-n20-plus-5-v1",
        model=model,
        prompts=prompts,
    )
