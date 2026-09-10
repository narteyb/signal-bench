# SPDX-License-Identifier: Apache-2.0
"""Keyword spotting task definition."""

from __future__ import annotations

from pathlib import Path

from signal_bench.adapters.mcu.task import TaskSpec
from signal_bench.tasks._manifest import read_task_paths
from signal_bench.tasks._registry import register_task


@register_task
def kws() -> TaskSpec:
    """Return the Post 1 keyword spotting task spec."""
    paths = read_task_paths("kws")
    return TaskSpec(
        task_id="kws",
        model_path=paths["tflite"],
        input_data_path=Path("phase5/inputs/kws_mfcc_int8.bin"),
        expected_output_shape=(1, 12),
        metadata={
            "name": "kws",
            "display_name": "Keyword Spotting",
            "family": "keyword_spotting",
            "architecture": "DS-CNN",
            "dataset": "Speech Commands",
            "input_shape": (1, 49, 10, 1),
            "input_dtype": "int8",
            "output_shape": (1, 12),
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
