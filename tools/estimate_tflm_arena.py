#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Estimate TFLM tensor arena budgets for the Post 1 reference models.

This is a static pre-hardware estimate. TensorFlow Lite for Microcontrollers
reports exact arena usage from firmware via RecordingMicroAllocator; LiteRT's
Python interpreter does not expose that value, so this script uses tensor
metadata to produce a conservative planning number.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from ai_edge_litert.interpreter import Interpreter  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ModelSpec:
    """Input model artifact to inspect."""

    task: str
    path: Path


@dataclass(frozen=True)
class ArenaEstimate:
    """Estimated static and runtime memory budget for one model."""

    task: str
    model_bytes: int
    input_bytes: int
    output_bytes: int
    largest_runtime_tensor_bytes: int
    runtime_tensor_bytes_sum: int
    estimated_arena_bytes: int


MODEL_SPECS = (
    ModelSpec("kws", REPO_ROOT / "models/reference/kws/kws_ref_model.tflite"),
    ModelSpec("ic", REPO_ROOT / "models/reference/ic/pretrainedResnet_quant.tflite"),
    ModelSpec("ad", REPO_ROOT / "models/reference/ad/ad01_int8.tflite"),
)


def _round_up(value: int, alignment: int) -> int:
    return int(math.ceil(value / alignment) * alignment)


TensorDetail = dict[str, Any]


def _tensor_shape(detail: TensorDetail) -> tuple[int, ...]:
    return tuple(int(x) for x in cast("Any", detail.get("shape", ())))


def _tensor_nbytes(detail: TensorDetail) -> int:
    shape = _tensor_shape(detail)
    count = math.prod(shape) if shape else 1
    dtype = np.dtype(detail["dtype"])
    return int(count * dtype.itemsize)


def _is_runtime_tensor(detail: TensorDetail) -> bool:
    """Return true for inputs, outputs, and intermediate activations.

    TFLite tensor metadata also includes constant weights and biases. Those
    bytes are part of the model FlatBuffer in Flash, not the SRAM tensor arena.
    """
    shape = _tensor_shape(detail)
    name = str(detail["name"])
    if shape and shape[0] == 1:
        return True
    runtime_name_markers = (
        "input",
        "Identity",
        "activation",
        "/Relu",
        "/add",
        "BiasAdd;",
    )
    return any(marker in name for marker in runtime_name_markers)


def estimate_model(spec: ModelSpec) -> ArenaEstimate:
    """Estimate a conservative tensor-arena budget from TFLite tensor metadata."""
    interpreter = Interpreter(model_path=str(spec.path))
    interpreter.allocate_tensors()

    input_indexes = {int(item["index"]) for item in interpreter.get_input_details()}
    output_indexes = {int(item["index"]) for item in interpreter.get_output_details()}

    runtime_sizes: list[int] = []
    input_bytes = 0
    output_bytes = 0
    for detail in interpreter.get_tensor_details():
        size = _tensor_nbytes(detail)
        index = int(detail["index"])
        if index in input_indexes:
            input_bytes += size
        if index in output_indexes:
            output_bytes += size
        if _is_runtime_tensor(detail):
            runtime_sizes.append(size)

    largest_runtime = max(runtime_sizes)
    runtime_sum = sum(runtime_sizes)

    # Conservative fallback heuristic:
    # - at least three copies of the largest live tensor plus scratch space,
    #   covering input/output/current-layer overlap and common kernel scratch;
    # - at least one third of runtime tensor bytes plus scratch, covering graphs
    #   with residual branches where more than one activation stays live.
    scratch_bytes = 8 * 1024
    lower_bound_a = largest_runtime * 3 + scratch_bytes
    lower_bound_b = int(runtime_sum * 0.33) + scratch_bytes
    estimate = _round_up(max(lower_bound_a, lower_bound_b), 4096)

    return ArenaEstimate(
        task=spec.task,
        model_bytes=spec.path.stat().st_size,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        largest_runtime_tensor_bytes=largest_runtime,
        runtime_tensor_bytes_sum=runtime_sum,
        estimated_arena_bytes=estimate,
    )


def main() -> None:
    """Print CSV arena estimates for the reference models."""
    sys.stdout.write(
        "task,model_bytes,input_bytes,output_bytes,largest_runtime_tensor_bytes,"
        "runtime_tensor_bytes_sum,estimated_arena_bytes\n",
    )
    for spec in MODEL_SPECS:
        estimate = estimate_model(spec)
        sys.stdout.write(
            f"{estimate.task},{estimate.model_bytes},{estimate.input_bytes},"
            f"{estimate.output_bytes},{estimate.largest_runtime_tensor_bytes},"
            f"{estimate.runtime_tensor_bytes_sum},{estimate.estimated_arena_bytes}\n",
        )


if __name__ == "__main__":
    main()
