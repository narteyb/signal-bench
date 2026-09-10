# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from signal_bench_cli.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path


def _lineage(tmp_path: Path, *, delta_pp: float = -1.0) -> Path:
    path = tmp_path / "lineage.json"
    path.write_text(
        json.dumps(
            {
                "derived_from": "tinyml-kws-ds-cnn-ref-v1",
                "prep_method": "quantization-aware-training",
                "prep_params": {"target_dtype": "int8"},
                "accuracy_retention": {
                    "metric": "top1",
                    "canonical": 0.943,
                    "variant": 0.935,
                    "delta_pp": delta_pp,
                },
                "prep_pipeline_uri": "variant-pipeline://model-prep/v1/kws",
            },
        ),
        encoding="utf-8",
    )
    return path


def test_model_lineage_required_for_n3_and_rejected_for_other_corpora(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "lineage.db"
    lineage = _lineage(tmp_path)

    missing = runner.invoke(
        main,
        [
            "run",
            "--task",
            "kws",
            "--target",
            "mock",
            "--runs",
            "1",
            "--corpus",
            "N3",
            "--db",
            str(db_path),
        ],
    )
    assert missing.exit_code == 3
    assert "--model-lineage is required" in missing.output

    rejected = runner.invoke(
        main,
        [
            "run",
            "--task",
            "kws",
            "--target",
            "mock",
            "--runs",
            "1",
            "--corpus",
            "X",
            "--model-lineage",
            str(lineage),
            "--db",
            str(db_path),
        ],
    )
    assert rejected.exit_code == 3
    assert "--model-lineage is only valid" in rejected.output


def test_model_lineage_schema_validation_and_acceptance(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "accepted.db"
    malformed = tmp_path / "bad.json"
    malformed.write_text('{"derived_from": "missing required keys"}', encoding="utf-8")

    failed = runner.invoke(
        main,
        [
            "run",
            "--task",
            "kws",
            "--target",
            "mock",
            "--runs",
            "1",
            "--corpus",
            "N3",
            "--model-lineage",
            str(malformed),
            "--db",
            str(db_path),
        ],
    )
    assert failed.exit_code == 3
    assert "missing required keys" in failed.output

    lineage = _lineage(tmp_path)
    accepted = runner.invoke(
        main,
        [
            "run",
            "--task",
            "kws",
            "--target",
            "mock",
            "--runs",
            "1",
            "--corpus",
            "N3",
            "--model-lineage",
            str(lineage),
            "--db",
            str(db_path),
        ],
    )
    assert accepted.exit_code == 0, accepted.output

    inspected = runner.invoke(main, ["inspect", "--db", str(db_path), "--corpus", "N3"])
    assert inspected.exit_code == 0, inspected.output
    assert "N3" in inspected.output
