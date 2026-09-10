# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from signal_bench.tasks._manifest import MANIFEST_PATH, read_task_paths


def test_manifest_path_exists() -> None:
    assert MANIFEST_PATH.exists()


def test_read_task_paths_resolves_artifact_paths() -> None:
    paths = read_task_paths("kws")

    assert paths["tflite"].exists()
    assert paths["onnx"].exists()
    assert paths["tflm_c_array"].exists()
    assert isinstance(paths["tflite"], Path)
    assert len(paths["sha256"]) == 64


def test_read_task_paths_unknown_task_lists_available_tasks() -> None:
    try:
        read_task_paths("missing")
    except KeyError as exc:
        message = str(exc)
    else:
        msg = "expected KeyError"
        raise AssertionError(msg)

    assert "Unknown task in manifest" in message
    assert "kws" in message
