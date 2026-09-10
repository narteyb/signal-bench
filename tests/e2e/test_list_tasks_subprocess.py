# SPDX-License-Identifier: Apache-2.0
"""Subprocess E2E tests for `signal-bench list-tasks`."""

from __future__ import annotations

import subprocess


def test_list_tasks_via_subprocess_shows_registered_tasks() -> None:
    result = subprocess.run(
        ["signal-bench", "list-tasks"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "kws" in result.stdout
    assert "ic" in result.stdout
    assert "ad" in result.stdout
