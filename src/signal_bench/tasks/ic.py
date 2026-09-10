# SPDX-License-Identifier: Apache-2.0
"""Image classification task definition."""

from __future__ import annotations

from pathlib import Path

from signal_bench.adapters.mcu.task import TaskSpec
from signal_bench.tasks._manifest import read_task_paths
from signal_bench.tasks._registry import register_task


@register_task
def ic() -> TaskSpec:
    """Return the Post 1 image classification task spec."""
    paths = read_task_paths("ic")
    return TaskSpec(
        task_id="ic",
        model_path=paths["tflite"],
        input_data_path=Path("phase5/inputs/ic_cifar10_int8.bin"),
        expected_output_shape=(1, 10),
        metadata={
            "name": "ic",
            "display_name": "Image Classification",
            "family": "image_classification",
            "architecture": "ResNet-8",
            "dataset": "CIFAR-10",
            "input_shape": (1, 32, 32, 3),
            "input_dtype": "int8",
            "output_shape": (1, 10),
            "output_dtype": "int8",
            "quantization": "int8",
            "model_hash": paths["sha256"],
            "model_bytes": paths["bytes"],
            "formats": {
                "tflite": paths["tflite"],
                "tflm_c_array": paths["tflm_c_array"],
                "onnx": paths["onnx"],
            },
            "targets": paths["targets"],
        },
    )
