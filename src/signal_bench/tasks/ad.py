# SPDX-License-Identifier: Apache-2.0
"""Anomaly detection task definition."""

from __future__ import annotations

from pathlib import Path

from signal_bench.adapters.mcu.task import TaskSpec
from signal_bench.tasks._manifest import read_task_paths
from signal_bench.tasks._registry import register_task


@register_task
def ad() -> TaskSpec:
    """Return the Post 1 anomaly detection task spec."""
    paths = read_task_paths("ad")
    return TaskSpec(
        task_id="ad",
        model_path=paths["tflite"],
        input_data_path=Path("phase5/inputs/ad_toyadmos_int8.bin"),
        expected_output_shape=(1, 640),
        metadata={
            "name": "ad",
            "display_name": "Anomaly Detection",
            "family": "anomaly_detection",
            "architecture": "Dense Autoencoder",
            "dataset": "ToyADMOS",
            "input_shape": (1, 640),
            "input_dtype": "int8",
            "output_shape": (1, 640),
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
