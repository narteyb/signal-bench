# SPDX-License-Identifier: Apache-2.0
"""Subprocess E2E tests for `signal-bench init`."""

from __future__ import annotations

import sqlite3
import subprocess


def test_init_via_console_script_creates_database(tmp_path) -> None:
    """Verify console_scripts wiring and schema creation from a fresh process."""
    db_path = tmp_path / "signal-bench.db"

    result = subprocess.run(
        ["signal-bench", "init", "--db", str(db_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert db_path.exists()
    assert "Database created" in result.stdout
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
    assert {"targets", "tasks", "runs", "results", "telemetry_samples"} <= tables


def test_init_existing_database_without_force_fails_via_subprocess(tmp_path) -> None:
    """Verify user-facing duplicate database errors from the installed entry point."""
    db_path = tmp_path / "signal-bench.db"
    first = subprocess.run(
        ["signal-bench", "init", "--db", str(db_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    second = subprocess.run(
        ["signal-bench", "init", "--db", str(db_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 1
    assert "Database already exists" in second.stdout
    assert "--force" in second.stdout
