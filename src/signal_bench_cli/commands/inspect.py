# SPDX-License-Identifier: Apache-2.0
"""`signal-bench inspect`: narrow Phase 5 session review queries."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import click
from alembic import command
from alembic.config import Config
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from signal_bench.schema import ACTIVE_CORPUS_TAGS, Failure, Run, Target, Task

console = Console()


@click.command(name="inspect")
@click.option(
    "--db",
    "db_path",
    default="./signal-bench.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the SQLite database file.",
)
@click.option("--session", "session_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--corpus", "corpus_tag", type=click.Choice(ACTIVE_CORPUS_TAGS))
@click.option("--target", "target_name")
@click.option("--task", "task_id")
@click.option("--failures", "show_failures", is_flag=True)
def inspect_cmd(  # noqa: PLR0913 - Click command callback.
    db_path: Path,
    session_date: dt.datetime | None,
    corpus_tag: str | None,
    target_name: str | None,
    task_id: str | None,
    show_failures: bool,  # noqa: FBT001 - Click passes flag values positionally.
) -> None:
    """Inspect Phase 5 runs or first-class failure records."""
    _ensure_database(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        with session_factory() as session:
            if show_failures:
                _print_failures(session, session_date, target_name, task_id)
            else:
                _print_runs(session, session_date, corpus_tag, target_name, task_id)
    finally:
        engine.dispose()


def _print_runs(
    session: Session,
    session_date: dt.datetime | None,
    corpus_tag: str | None,
    target_name: str | None,
    task_id: str | None,
) -> None:
    statement = select(Run, Target, Task).join(Target).join(Task)
    if session_date is not None:
        start, end = _day_bounds(session_date)
        statement = statement.where(Run.started_at >= start, Run.started_at < end)
    if corpus_tag is not None:
        statement = statement.where(Run.corpus_tag == corpus_tag)
    if target_name is not None:
        statement = statement.where(Target.name == target_name)
    if task_id is not None:
        statement = statement.where(Task.name == task_id)

    table = Table(title="signal-bench runs")
    table.add_column("run_id")
    table.add_column("session")
    table.add_column("corpus")
    table.add_column("target")
    table.add_column("task")
    table.add_column("status")
    for run, target, task in session.execute(statement.order_by(Run.started_at)).all():
        table.add_row(
            run.run_id,
            run.started_at.date().isoformat(),
            run.corpus_tag,
            target.name,
            task.name,
            run.status,
        )
    console.print(table)


def _print_failures(
    session: Session,
    session_date: dt.datetime | None,
    target_name: str | None,
    task_id: str | None,
) -> None:
    statement = select(Failure, Target, Task).join(Target).join(Task)
    if session_date is not None:
        start, end = _day_bounds(session_date)
        statement = statement.where(Failure.attempted_at >= start, Failure.attempted_at < end)
    if target_name is not None:
        statement = statement.where(Target.name == target_name)
    if task_id is not None:
        statement = statement.where(Task.name == task_id)

    table = Table(title="signal-bench failures")
    table.add_column("failure_id")
    table.add_column("session")
    table.add_column("corpus")
    table.add_column("target")
    table.add_column("task")
    table.add_column("mode", overflow="fold")
    modes: list[str] = []
    for failure, target, task in session.execute(statement.order_by(Failure.attempted_at)).all():
        modes.append(failure.failure_mode)
        table.add_row(
            failure.failure_id,
            failure.attempted_at.date().isoformat(),
            failure.corpus_tag,
            target.name,
            task.name,
            failure.failure_mode,
        )
    console.print(table)
    if modes:
        console.print("failure modes: {}".format(", ".join(sorted(set(modes)))))


def _day_bounds(value: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(value.date(), dt.time.min)
    return start, start + dt.timedelta(days=1)


def _ensure_database(db_path: Path) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
