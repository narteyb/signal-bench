# SPDX-License-Identifier: Apache-2.0
"""Subprocess E2E tests for `signal-bench telemetry`."""

from __future__ import annotations

import json
import signal
import sqlite3
import subprocess
import time


def test_telemetry_sources_via_subprocess_lists_mock(tmp_path) -> None:
    """Verify the telemetry sources command works through console_scripts wiring."""
    db_path = tmp_path / "signal-bench.db"

    result = subprocess.run(
        ["signal-bench", "telemetry", "sources", "--db", str(db_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "mock" in result.stdout
    assert "available" in result.stdout


def test_telemetry_test_mock_via_subprocess_writes_samples(tmp_path) -> None:
    """Verify telemetry test side effects from a fresh shell process."""
    db_path = tmp_path / "signal-bench.db"

    result = subprocess.run(
        [
            "signal-bench",
            "telemetry",
            "test",
            "--duration",
            "1",
            "--no-fnb58",
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Telemetry Test Summary" in result.stdout
    assert "mock_ina219_main" in result.stdout
    with sqlite3.connect(db_path) as connection:
        sample_count = connection.execute("SELECT COUNT(*) FROM telemetry_samples").fetchone()[0]
        completed_runs = connection.execute(
            "SELECT COUNT(*) FROM runs WHERE status = 'completed'",
        ).fetchone()[0]
    assert sample_count >= 45
    assert completed_runs == 1


def test_telemetry_test_json_output_via_subprocess(tmp_path) -> None:
    """Verify JSON output is machine-readable through console_scripts wiring."""
    db_path = tmp_path / "signal-bench.db"

    result = subprocess.run(
        [
            "signal-bench",
            "telemetry",
            "test",
            "--duration",
            "1",
            "--no-fnb58",
            "--quiet",
            "--output",
            "json",
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["telemetry_partial"] is False
    assert summary["skipped_sources"] == ["fnb58"]
    assert {source["source"] for source in summary["sources"]} == {
        "mock_ina219_main",
        "mock_bme280_lab",
    }


def test_telemetry_test_sigint_gracefully_stops_via_subprocess(tmp_path) -> None:
    """Verify Ctrl-C stops the orchestrator and marks the run interrupted."""
    db_path = tmp_path / "signal-bench.db"
    process = subprocess.Popen(
        [
            "signal-bench",
            "telemetry",
            "test",
            "--duration",
            "30",
            "--no-fnb58",
            "--db",
            str(db_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    time.sleep(2.0)
    process.send_signal(signal.SIGINT)
    stdout, stderr = process.communicate(timeout=15)

    assert process.returncode == 0, stderr
    assert "Interrupted by user" in stdout
    assert "Telemetry Test Summary" in stdout
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT status, telemetry_partial FROM runs").fetchall()
    assert rows == [("interrupted", 0)]
