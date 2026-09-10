# SPDX-License-Identifier: Apache-2.0
"""signal-bench CLI entry point."""

import click

from signal_bench import __version__
from signal_bench_cli.commands.eval import eval_cmd
from signal_bench_cli.commands.init import init_cmd
from signal_bench_cli.commands.inspect import inspect_cmd
from signal_bench_cli.commands.list_tasks import list_tasks_cmd
from signal_bench_cli.commands.phase1 import phase1_group
from signal_bench_cli.commands.run import run_cmd
from signal_bench_cli.commands.spot_check import spot_check_cmd
from signal_bench_cli.commands.synth import synth_group
from signal_bench_cli.commands.telemetry import telemetry_group


@click.group()
@click.version_option(__version__, prog_name="signal-bench")
def main() -> None:
    """signal-bench: edge AI benchmarking that ships."""


main.add_command(init_cmd)
main.add_command(eval_cmd)
main.add_command(inspect_cmd)
main.add_command(list_tasks_cmd)
main.add_command(phase1_group)
main.add_command(run_cmd)
main.add_command(spot_check_cmd)
main.add_command(synth_group)
main.add_command(telemetry_group)

if __name__ == "__main__":
    main()
