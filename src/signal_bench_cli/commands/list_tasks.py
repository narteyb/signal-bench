# SPDX-License-Identifier: Apache-2.0
"""`signal-bench list-tasks`: show registered benchmark tasks."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from signal_bench.tasks import get_task, list_tasks

console = Console()


@click.command(name="list-tasks")
def list_tasks_cmd() -> None:
    """List Post 1 tasks available to `signal-bench run`."""
    table = Table(title="Available Tasks", show_lines=False, header_style="bold")
    table.add_column("Task")
    table.add_column("Family")
    table.add_column("Model")
    table.add_column("Input")
    table.add_column("Output")

    for name in list_tasks():
        task = get_task(name)
        metadata = task.metadata
        table.add_row(
            task.task_id,
            str(metadata["family"]),
            f"{metadata['architecture']} ({metadata['quantization']})",
            f"{metadata['input_shape']} {metadata['input_dtype']}",
            f"{metadata['output_shape']} {metadata['output_dtype']}",
        )

    console.print(table)
