# SPDX-License-Identifier: Apache-2.0
from signal_bench.tasks import get_task


def test_kws_task_spec_matches_reference_manifest() -> None:
    task = get_task("kws")

    assert task.task_id == "kws"
    assert task.model_path.exists()
    assert task.expected_output_shape == (1, 12)
    assert task.metadata["family"] == "keyword_spotting"
    assert task.metadata["input_shape"] == (1, 49, 10, 1)
    assert task.metadata["output_shape"] == (1, 12)
    assert task.metadata["quantization"] == "int8"
    assert len(str(task.metadata["model_hash"])) == 64
