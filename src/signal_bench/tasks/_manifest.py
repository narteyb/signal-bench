# SPDX-License-Identifier: Apache-2.0
"""Manifest helpers for Post 1 task definitions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "models/reference/manifest.yaml"


def read_task_paths(task_name: str) -> dict[str, Any]:
    """Return model paths, hashes, and target-fit metadata for one task."""
    tasks = _manifest_tasks()
    try:
        info = tasks[task_name]
    except KeyError as exc:
        available = ", ".join(sorted(tasks))
        msg = f"Unknown task in manifest: {task_name}. Available: {available}"
        raise KeyError(msg) from exc

    formats = cast("dict[str, Any]", info["formats"])
    return {
        "tflite": _resolve_reference_path(cast("str", formats["tflite"]["path"])),
        "tflm_c_array": _resolve_reference_path(
            cast("str", formats["tflm_c_array"]["path"]),
        ),
        "onnx": _resolve_reference_path(cast("str", formats["onnx"]["path"])),
        "sha256": cast("str", info["sha256"]),
        "bytes": int(info["bytes"]),
        "targets": cast("dict[str, Any]", info["targets"]),
    }


@lru_cache(maxsize=1)
def _read_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        return cast("dict[str, Any]", yaml.safe_load(handle))


def _manifest_tasks() -> dict[str, dict[str, Any]]:
    manifest = _read_manifest()
    return cast("dict[str, dict[str, Any]]", manifest["tasks"])


def _resolve_reference_path(raw_path: str) -> Path:
    return (MANIFEST_PATH.parent / raw_path).resolve()
