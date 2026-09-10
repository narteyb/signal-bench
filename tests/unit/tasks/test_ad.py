# SPDX-License-Identifier: Apache-2.0
from signal_bench.tasks import get_task


def test_ad_task_spec_matches_reference_manifest() -> None:
    task = get_task("ad")

    assert task.task_id == "ad"
    assert task.model_path.exists()
    assert task.expected_output_shape == (1, 640)
    assert task.metadata["family"] == "anomaly_detection"
    assert task.metadata["input_shape"] == (1, 640)
    assert task.metadata["output_shape"] == (1, 640)
    assert task.metadata["quantization"] == "int8"
    assert len(str(task.metadata["model_hash"])) == 64
