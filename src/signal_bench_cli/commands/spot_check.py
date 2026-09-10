# SPDX-License-Identifier: Apache-2.0
"""`signal-bench spot-check`: pre-protocol parity helpers."""

from __future__ import annotations

from pathlib import Path

import click
from alembic import command
from alembic.config import Config
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from signal_bench.schema import Run, Target, Task

console = Console()


@click.command(name="spot-check")
@click.option(
    "--db",
    "db_path",
    default="./signal-bench.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the SQLite database file.",
)
@click.option("--pre-protocol", "pre_protocol", is_flag=True, help="List legacy rows.")
def spot_check_cmd(db_path: Path, pre_protocol: bool) -> None:  # noqa: FBT001
    """Suggest representative legacy cells for parity re-measurement."""
    if not pre_protocol:
        click.echo("Use --pre-protocol to list legacy rows.")
        return

    _ensure_database(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        with session_factory() as session:
            rows = session.execute(
                select(Run, Target, Task)
                .join(Target)
                .join(Task)
                .where(Run.extra["pre_protocol"].as_boolean().is_(True))
                .order_by(Target.name, Task.name, Run.started_at),
            ).all()
    finally:
        engine.dispose()

    representatives: dict[tuple[str, str], tuple[Run, Target, Task]] = {}
    for run, target, task in rows:
        representatives.setdefault((target.target_id, task.task_id), (run, target, task))

    table = Table(title="pre-protocol parity spot-check candidates")
    table.add_column("target")
    table.add_column("task")
    table.add_column("run_id")
    table.add_column("started_at")
    for run, target, task in representatives.values():
        table.add_row(target.name, task.name, run.run_id, run.started_at.isoformat())
    console.print(table)


def _ensure_database(db_path: Path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
