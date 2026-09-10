# SPDX-License-Identifier: Apache-2.0
"""`signal-bench eval`: run full streamed-sample MCU accuracy evaluation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console

from signal_bench.artifacts import ensure_artifact
from signal_bench.eval import EvalRunConfig, FullEvalProtocolError, run_full_eval

console = Console()


@click.command(name="eval")
@click.option(
    "--db",
    "db_path",
    default="./data/p3_mcu_matrix.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the SQLite database file.",
)
@click.option("--task", "task_name", required=True, type=click.Choice(["kws", "ad"]))
@click.option("--target", "target_name", required=True)
@click.option("--corpus", "corpus_tag", required=True)
@click.option(
    "--data",
    "data_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Preprocessed int8 eval archive. Defaults to data/eval/<task>/<corpus>.npz.",
)
@click.option(
    "--serial-port",
    help="USB-CDC serial port. If omitted, target.extra.serial_port is read from the DB.",
)
@click.option("--baud-rate", default=115_200, show_default=True, type=int)
@click.option(
    "--runs-dir",
    default="./runs",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory for per-sample prediction CSVs.",
)
def eval_cmd(  # noqa: PLR0913 - Click command callback.
    db_path: Path,
    task_name: str,
    target_name: str,
    corpus_tag: str,
    data_path: Path | None,
    serial_port: str | None,
    baud_rate: int,
    runs_dir: Path,
) -> None:
    """Run full on-device KWS or AD evaluation on an MCU."""
    archive = data_path or Path("data") / "eval" / task_name / f"{corpus_tag}.npz"
    if data_path is None and not archive.exists():
        archive = ensure_artifact(archive)
    try:
        summary = asyncio.run(
            run_full_eval(
                EvalRunConfig(
                    db_path=db_path,
                    task=task_name,
                    target=target_name,
                    corpus=corpus_tag,
                    data_path=archive,
                    serial_port=serial_port,
                    baud_rate=baud_rate,
                    runs_dir=runs_dir,
                )
            )
        )
    except FullEvalProtocolError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(
        f"{summary['target']} {summary['task']} {summary['metric']}="
        f"{summary['value']:.6f} n={summary['n_samples']}"
    )
    console.print(f"Run ID: {summary['run_id']}")
    console.print(f"Per-sample CSV: {summary['per_sample_csv']}")
