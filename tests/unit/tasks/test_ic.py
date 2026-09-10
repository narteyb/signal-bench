# SPDX-License-Identifier: Apache-2.0
from signal_bench.tasks import get_task


def test_ic_task_spec_matches_reference_manifest() -> None:
    task = get_task("ic")

    assert task.task_id == "ic"
    assert task.model_path.exists()
    assert task.expected_output_shape == (1, 10)
    assert task.metadata["family"] == "image_classification"
    assert task.metadata["input_shape"] == (1, 32, 32, 3)
    assert task.metadata["output_shape"] == (1, 10)
    assert task.metadata["quantization"] == "int8"
    assert len(str(task.metadata["model_hash"])) == 64
