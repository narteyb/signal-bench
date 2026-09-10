# SPDX-License-Identifier: Apache-2.0
"""Subprocess E2E tests for `signal-bench run`."""

from __future__ import annotations

import sqlite3
import subprocess


def test_run_mock_via_subprocess_writes_run(tmp_path) -> None:
    db_path = tmp_path / "signal-bench.db"

    result = subprocess.run(
        [
            "signal-bench",
            "run",
            "--task",
            "kws",
            "--target",
            "mock",
            "--runs",
            "2",
            "--corpus",
            "X",
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Running kws on mock for 2 inferences" in result.stdout
    with sqlite3.connect(db_path) as connection:
        run = connection.execute(
            "SELECT model_name, model_hash, quantization, status FROM runs",
        ).fetchone()
        result_count = connection.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    assert run[0] == "kws"
    assert len(run[1]) == 64
    assert run[2] == "int8"
    assert run[3] == "completed"
    assert result_count == 2
