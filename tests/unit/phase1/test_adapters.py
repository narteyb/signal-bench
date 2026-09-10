# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from signal_bench.phase1.adapters import (
    LlamaCppAdapterConfig,
    LlamaCppRuntimeAdapter,
    _extract_llama_cli_answer,
    hailo_hef_adapter,
    jetson_tensorrt_llm_adapter,
    pi_llama_cpp_adapter,
)
from signal_bench.phase1.runtime import DecodeParams, GenerationRequest, HardwareRequired


@pytest.mark.parametrize(
    ("factory", "target", "backend"),
    [
        (pi_llama_cpp_adapter, "pi5-8gb", "pi5-cpu-llama.cpp"),
        (jetson_tensorrt_llm_adapter, "jetson-orin-nano-super", "jetson-cuda-tensorrt-llm"),
        (hailo_hef_adapter, "pi5-hailo10h", "hailo10h-hef"),
    ],
)
def test_device_adapters_stop_at_marked_hardware_seam(factory, target: str, backend: str) -> None:
    adapter = factory("example-model")
    metadata = adapter.metadata()

    assert metadata.target_name == target
    assert metadata.backend == backend
    assert metadata.extra["interlock_required"] is True
    assert "hardware_seam" in metadata.extra
    with pytest.raises(HardwareRequired):
        adapter.generate(
            GenerationRequest(
                prompt_id="p",
                prompt="hello",
                decode=DecodeParams(max_tokens=1),
            ),
        )


def test_llama_cpp_output_parser_extracts_single_turn_answer() -> None:
    prompt = "Answer with only the four-digit year."
    raw = f"""
Loading model...
build      : b9550-f0156d140
model      : sha256-example
modalities : text

> {prompt}

1889

[ Prompt: 309.1 t/s | Generation: 59.8 t/s ]

Exiting...
"""

    assert _extract_llama_cli_answer(raw, prompt) == "1889"


def test_llama_cpp_metadata_uses_explicit_model_path(tmp_path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"gguf-test")

    adapter = LlamaCppRuntimeAdapter(
        LlamaCppAdapterConfig(
            model="local-test",
            model_path=model,
            warmup=False,
        ),
    )
    metadata = adapter.metadata()

    assert metadata.runtime_name == "llama.cpp"
    assert metadata.model_name == "local-test"
    assert metadata.model_bytes == len(b"gguf-test")
    assert metadata.extra["model_path"] == str(model)
    assert metadata.extra["warmup_excluded"] is True
