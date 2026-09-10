# SPDX-License-Identifier: Apache-2.0
"""`signal-bench init`: create database and run migrations."""

from pathlib import Path

import click
from alembic import command
from alembic.config import Config
from rich.console import Console

console = Console()


@click.command(name="init")
@click.option(
    "--db",
    "db_path",
    default="./signal-bench.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the SQLite database file.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Recreate the database even if it already exists.",
)
def init_cmd(db_path: Path, force: bool) -> None:
    """Create the signal-bench database and run all migrations."""
    if db_path.exists() and not force:
        console.print(f"[red]x[/red] Database already exists at [bold]{db_path}[/bold].")
        console.print("  Use [cyan]--force[/cyan] to recreate.")
        raise click.exceptions.Exit(1)

    if db_path.exists() and force:
        db_path.unlink()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")

    console.print(f"[green]+[/green] Database created at [bold]{db_path}[/bold] with 5 tables.")
