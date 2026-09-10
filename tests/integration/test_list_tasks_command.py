# SPDX-License-Identifier: Apache-2.0
from click.testing import CliRunner

from signal_bench_cli.__main__ import main


def test_list_tasks_command_shows_registered_tasks() -> None:
    result = CliRunner().invoke(main, ["list-tasks"])

    assert result.exit_code == 0, result.output
    assert "Available Tasks" in result.output
    assert "kws" in result.output
    assert "ic" in result.output
    assert "ad" in result.output
