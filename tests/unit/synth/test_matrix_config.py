# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest
import yaml

from signal_bench.synth.matrix_config import MatrixConfigError, load_matrix_config


def _write_config(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _minimal_config() -> dict:
    return {
        "schema_version": 1,
        "name": "test-matrix",
        "version": "1.0.0",
        "description": "test",
        "created": "2026-05-10",
        "tasks": ["kws"],
        "targets": ["mock"],
        "defaults": {
            "iterations": 100,
            "warmup_iterations": 10,
            "latency_budget_ms": None,
            "accuracy_threshold": None,
            "energy_budget_uwh": None,
        },
        "cells": [{"task": "kws", "target": "mock", "accuracy_threshold": 0.81}],
        "exclusions": [],
    }


def test_loads_canonical_matrix_config() -> None:
    config = load_matrix_config("configs/matrix.yaml")

    assert config.name == "post-1-tinyml-matrix"
    assert config.tasks == ["kws", "ic", "ad"]
    assert config.targets == ["f401re", "nano33", "esp32s3", "pi5", "jetson", "m1max", "modal"]
    assert len(config.cells) == 21
    assert config.exclusions == []


def test_loads_minimal_valid_config(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _minimal_config())

    config = load_matrix_config(path)

    assert len(config.cells) == 1
    assert config.cells[0].task == "kws"


def test_loads_phase_5_overrides(tmp_path: Path) -> None:
    data = _minimal_config()
    data["phase_5_overrides"] = {
        "kws": {"mock": {"notes": "exercise override parsing"}},
    }
    path = _write_config(tmp_path, data)

    config = load_matrix_config(path)

    assert config.phase_5_overrides["kws"]["mock"]["notes"] == "exercise override parsing"


def test_rejects_missing_required_field(tmp_path: Path) -> None:
    data = _minimal_config()
    del data["cells"]
    path = _write_config(tmp_path, data)

    with pytest.raises(MatrixConfigError, match="Invalid matrix config"):
        load_matrix_config(path)


def test_rejects_bad_accuracy_threshold(tmp_path: Path) -> None:
    data = _minimal_config()
    data["cells"][0]["accuracy_threshold"] = 1.5
    path = _write_config(tmp_path, data)

    with pytest.raises(MatrixConfigError, match="accuracy_threshold"):
        load_matrix_config(path)


def test_rejects_unknown_task(tmp_path: Path) -> None:
    data = _minimal_config()
    data["tasks"] = ["unknown"]
    data["cells"] = [{"task": "unknown", "target": "mock"}]
    path = _write_config(tmp_path, data)

    with pytest.raises(MatrixConfigError, match="unknown tasks"):
        load_matrix_config(path)


def test_rejects_unknown_target(tmp_path: Path) -> None:
    data = _minimal_config()
    data["targets"] = ["bad-target"]
    data["cells"] = [{"task": "kws", "target": "bad-target"}]
    path = _write_config(tmp_path, data)

    with pytest.raises(MatrixConfigError, match="unknown targets"):
        load_matrix_config(path)


def test_rejects_duplicate_cell_and_schema_mismatch(tmp_path: Path) -> None:
    duplicate = _minimal_config()
    duplicate["cells"] = [
        {"task": "kws", "target": "mock"},
        {"task": "kws", "target": "mock"},
    ]
    with pytest.raises(MatrixConfigError, match="duplicate cell"):
        load_matrix_config(_write_config(tmp_path, duplicate))

    mismatch = _minimal_config()
    mismatch["schema_version"] = 2
    with pytest.raises(MatrixConfigError, match="unsupported matrix schema_version"):
        load_matrix_config(_write_config(tmp_path, mismatch))
