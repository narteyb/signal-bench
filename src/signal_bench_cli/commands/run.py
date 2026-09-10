# SPDX-License-Identifier: Apache-2.0
"""`signal-bench run`: dispatch a task to the library orchestrator."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console

from signal_bench.orchestrator import (
    CellSpec,
    Orchestrator,
    OrchestratorConfig,
    ProtocolError,
    ProtocolFailure,
    ProtocolGateRejected,
)
from signal_bench.schema import ACTIVE_CORPUS_TAGS

console = Console()
EXIT_OK = 0
EXIT_CONFIG_ERROR = 3
EXIT_DB_ERROR = 4


@click.command(name="run")
@click.option(
    "--db",
    "db_path",
    default="./signal-bench.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the SQLite database file.",
)
@click.option(
    "--task",
    "task_name",
    required=True,
    help="Task name. Use `signal-bench list-tasks` to see available tasks.",
)
@click.option(
    "--target",
    "target_name",
    required=True,
    help="Adapter target name. T2.6 supports `mock`; Phase 5 adds hardware targets.",
)
@click.option(
    "--runs",
    "iterations",
    required=True,
    type=int,
    help="Number of inferences to run.",
)
@click.option(
    "--corpus",
    "corpus_tag",
    required=True,
    type=click.Choice(ACTIVE_CORPUS_TAGS),
    help="Required Phase 5 corpus tag. Allowed values: X, N1, N3, N4.",
)
@click.option(
    "--model-lineage",
    "model_lineage_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="N3 model-lineage JSON. Required for --corpus N3 and rejected otherwise.",
)
def run_cmd(  # noqa: PLR0913 - Click command callback.
    db_path: Path,
    task_name: str,
    target_name: str,
    iterations: int,
    corpus_tag: str,
    model_lineage_path: Path | None,
) -> None:
    """Run a task on a target adapter."""
    cell = CellSpec(
        task_name=task_name,
        target_name=target_name,
        iterations=iterations,
        corpus_tag=corpus_tag,
        model_lineage_path=model_lineage_path,
    )
    orchestrator: Orchestrator | None = None
    try:
        orchestrator = Orchestrator(
            OrchestratorConfig(db_path=db_path),
        )
        summary = asyncio.run(orchestrator.run_cell(cell))
    except (KeyError, ProtocolError, ProtocolGateRejected, ProtocolFailure) as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(EXIT_CONFIG_ERROR) from None
    except Exception as exc:  # noqa: BLE001 - Click boundary maps unexpected failures.
        click.echo(f"Failed to run benchmark cell: {exc}", err=True)
        raise click.exceptions.Exit(EXIT_DB_ERROR) from None
    finally:
        if orchestrator is not None:
            orchestrator.close()

    console.print(
        f"Running {task_name} on {summary.target_name} for {iterations} inferences...",
    )
    total_ms = summary.total_duration_us / 1000
    console.print(
        f"Result: {summary.count} inferences in {total_ms:.2f}ms "
        f"({summary.avg_duration_us:.0f}us/inference)",
    )
    console.print(f"Output hash: {summary.output_hash}")
    console.print(f"Run ID: {summary.run_id} (stored in DB)")
    raise click.exceptions.Exit(EXIT_OK)
