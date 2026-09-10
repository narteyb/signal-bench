# SPDX-License-Identifier: Apache-2.0
"""Subprocess E2E tests for the top-level CLI entry point."""

from __future__ import annotations

import subprocess


def test_signal_bench_version_via_subprocess() -> None:
    """Verify the installed console script exposes the package version."""
    result = subprocess.run(
        ["signal-bench", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "0.2.0.dev0" in result.stdout
