# SPDX-License-Identifier: Apache-2.0
"""signal-bench telemetry: observability into the telemetry layer."""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import json
import os
import signal
import time
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import click
from alembic import command
from alembic.config import Config
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Run, Target, Task
from signal_bench.schema import TelemetrySample as TelemetrySampleRow
from signal_bench.telemetry import (
    Bme280Config,
    Bme280Source,
    FnirsiHidSource,
    FnirsiHidSourceConfig,
    FnirsiSource,
    FnirsiSourceConfig,
    Ina219Config,
    Ina219Source,
    MockBME280Config,
    MockBME280Source,
    MockINA219Config,
    MockINA219Source,
    MockTelemetrySource,
    OrchestratorError,
    TelemetryError,
    TelemetryOrchestrator,
    TelemetrySource,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

console = Console()
OutputFormat = Literal["table", "json", "csv"]
EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_ORCHESTRATOR_FAILED = 2
EXIT_CONFIG_ERROR = 3
EXIT_DB_ERROR = 4
PROGRESS_INTERVAL_S = 10.0
REAL_TELEMETRY_ENV = "SIGNAL_BENCH_REAL_TELEMETRY"
REAL_I2C_ENV = "SIGNAL_BENCH_REAL_I2C"
INA219_ADDRESS_ENV = "INA219_ADDRESS"
BME280_ADDRESS_ENV = "BME280_ADDRESS"
FNB58_TRANSPORT_ENV = "FNB58_TRANSPORT"
FNB58_TRANSPORT_USB_HID = "usb_hid"
FNB58_TRANSPORT_BLE = "ble"
FNB58_TRANSPORT_CHOICES = {FNB58_TRANSPORT_USB_HID, FNB58_TRANSPORT_BLE}


@click.group(name="telemetry")
def telemetry_group() -> None:
    """Inspect and exercise the telemetry layer."""


@telemetry_group.command(name="sources")
@click.option(
    "--db",
    "_db_path",
    default="./signal-bench.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
def sources_cmd(_db_path: Path) -> None:
    """List configured telemetry sources and their availability."""
    table = Table(show_lines=False, header_style="bold")
    table.add_column("Source")
    table.add_column("Rate (Hz)", justify="right")
    table.add_column("Library")
    table.add_column("Hardware")
    table.add_column("Status")

    for source in _build_configured_sources():
        available = source.is_available()
        status = "[green]available[/green]" if available else "[dim]unavailable[/dim]"
        library = _source_library_label(source)
        hardware = _source_hardware_label(source)
        table.add_row(
            source.source_name,
            f"{source.sample_rate_hz:.1f}",
            library,
            hardware,
            status,
        )

    console.print(table)


@telemetry_group.command(name="test")
@click.option(
    "--db",
    "db_path",
    default="./signal-bench.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option(
    "--duration",
    type=int,
    help="Required. Duration to run, in seconds.",
)
@click.option(
    "--fnb58-address",
    default=None,
    help="BLE address of FNB58. Overrides FNB58_ADDRESS.",
)
@click.option(
    "--no-fnb58",
    is_flag=True,
    help="Skip FNB58 even if an address is available; run mocked sources only.",
)
@click.option(
    "--output",
    "output_format",
    type=click.Choice(("table", "json", "csv")),
    default="table",
    show_default=True,
    help="Summary output format.",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress progress output; final summary only.",
)
def test_cmd(
    db_path: Path,
    duration: int | None,
    fnb58_address: str | None,
    no_fnb58: bool,
    output_format: OutputFormat,
    quiet: bool,
) -> None:
    """Run the M2 Stage 1 telemetry roster.

    Exit codes: 0 clean run, 1 telemetry partial, 2 orchestrator failure,
    3 configuration error, 4 database error.
    """
    if duration is None or duration <= 0:
        click.echo("--duration must be a positive integer number of seconds.", err=True)
        raise click.exceptions.Exit(EXIT_CONFIG_ERROR)

    try:
        exit_code = asyncio.run(
            _run_telemetry_test(
                db_path=db_path,
                duration_s=duration,
                fnb58_address=fnb58_address,
                no_fnb58=no_fnb58,
                output_format=output_format,
                quiet=quiet,
            ),
        )
    except KeyboardInterrupt:
        click.echo("\nInterrupted by user.", err=True)
        raise click.exceptions.Exit(EXIT_ORCHESTRATOR_FAILED) from None

    raise click.exceptions.Exit(exit_code)


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """Post-run sample and row counts for one source."""

    source: str
    samples: int
    rows: int
    rate_hz: float
    status: str


@dataclass(frozen=True, slots=True)
class TelemetryTestSummary:
    """Final CLI summary for a telemetry test run."""

    run_id: str
    duration_s: float
    telemetry_partial: bool
    telemetry_partial_sources: list[str]
    sources: list[SourceSummary]
    skipped_sources: list[str]


async def _run_telemetry_test(
    *,
    db_path: Path,
    duration_s: int,
    fnb58_address: str | None,
    no_fnb58: bool,
    output_format: OutputFormat,
    quiet: bool,
) -> int:
    """Run one async telemetry test and print the requested summary."""
    try:
        _ensure_database(db_path)
        engine = create_engine(f"sqlite:///{db_path}")
        session_factory = sessionmaker(bind=engine)
    except Exception as exc:
        click.echo(f"Failed to open or migrate telemetry database: {exc}", err=True)
        return EXIT_DB_ERROR

    try:
        sources, skipped_sources = _build_stage1_sources(
            fnb58_address=fnb58_address,
            no_fnb58=no_fnb58,
            output_format=output_format,
            quiet=quiet,
        )
        run_id = _create_test_run(
            session_factory,
            duration_s=duration_s,
            source_names=[source.name for source in sources],
            skipped_sources=skipped_sources,
            fnb58_enabled=any(
                isinstance(source, FnirsiSource | FnirsiHidSource) for source in sources
            ),
        )
    except Exception as exc:
        click.echo(f"Failed to create telemetry test run: {exc}", err=True)
        engine.dispose()
        return EXIT_DB_ERROR

    orchestrator = TelemetryOrchestrator(session_factory)
    interrupt_event = asyncio.Event()
    restore_sigint_handler = _install_sigint_handler(interrupt_event)
    started_at = time.monotonic()
    exit_code = EXIT_OK
    status = "completed"
    try:
        if output_format == "table" and not quiet:
            _print_start(run_id, duration_s, sources, skipped_sources)
        await orchestrator.start_run(run_id, sources)
        await _wait_for_duration(
            duration_s=duration_s,
            orchestrator=orchestrator,
            quiet=quiet or output_format != "table",
            interrupt_event=interrupt_event,
        )
        if interrupt_event.is_set():
            status = "interrupted"
            if output_format == "table":
                console.print("\n[dim]Interrupted by user; stopping telemetry gracefully...[/dim]")
    except KeyboardInterrupt:
        status = "interrupted"
        if output_format == "table":
            console.print("\n[dim]Interrupted by user; stopping telemetry gracefully...[/dim]")
    except OrchestratorError as exc:
        status = "failed"
        exit_code = EXIT_ORCHESTRATOR_FAILED
        if output_format == "table":
            console.print(f"[red]Telemetry orchestrator failed:[/red] {exc}")
    except TelemetryError as exc:
        status = "failed"
        exit_code = EXIT_ORCHESTRATOR_FAILED
        if output_format == "table":
            console.print(f"[red]Telemetry source failed:[/red] {exc}")
    finally:
        try:
            state = await orchestrator.stop_run()
            if state.partial and exit_code == EXIT_OK:
                exit_code = EXIT_PARTIAL
        except OrchestratorError as exc:
            status = "failed"
            exit_code = EXIT_ORCHESTRATOR_FAILED
            if output_format == "table":
                console.print(f"[red]Telemetry orchestrator failed:[/red] {exc}")
        restore_sigint_handler()

    elapsed_s = time.monotonic() - started_at
    _finish_run(session_factory, run_id=run_id, status=status)
    summary = _build_summary(
        session_factory,
        run_id=run_id,
        duration_s=elapsed_s,
        expected_sources=[source.name for source in sources],
        skipped_sources=skipped_sources,
    )
    _print_summary(summary, output_format=output_format)
    engine.dispose()
    return exit_code


def _build_stage1_sources(
    *,
    fnb58_address: str | None,
    no_fnb58: bool,
    output_format: OutputFormat,
    quiet: bool,
) -> tuple[list[TelemetrySource], list[str]]:
    """Return the M2 Stage 1 source roster."""
    use_real_i2c = _env_flag(REAL_TELEMETRY_ENV) or _env_flag(REAL_I2C_ENV)
    if use_real_i2c:
        sources: list[TelemetrySource] = [
            Ina219Source(Ina219Config(address=_env_i2c_address(INA219_ADDRESS_ENV, 0x40))),
            Bme280Source(Bme280Config(address=_env_i2c_address(BME280_ADDRESS_ENV, 0x77))),
        ]
    else:
        sources = [
            MockINA219Source(MockINA219Config()),
            MockBME280Source(MockBME280Config()),
        ]
    skipped_sources: list[str] = []

    if no_fnb58:
        skipped_sources.append("fnb58")
        return sources, skipped_sources

    transport = _fnb58_transport()
    if transport == FNB58_TRANSPORT_USB_HID:
        sources.insert(0, FnirsiHidSource(FnirsiHidSourceConfig()))
        return sources, skipped_sources

    address = fnb58_address or os.environ.get("FNB58_ADDRESS")
    if address is None or not address.strip():
        skipped_sources.append("fnb58")
        if output_format == "table" and not quiet:
            console.print(
                "[yellow]Warning:[/yellow] FNB58_ADDRESS not set; running without FNB58 BLE.",
            )
        return sources, skipped_sources

    sources.insert(0, FnirsiSource(FnirsiSourceConfig(address=address.strip())))
    return sources, skipped_sources


def _print_start(
    run_id: str,
    duration_s: int,
    sources: Sequence[TelemetrySource],
    skipped_sources: Sequence[str],
) -> None:
    """Print the initial run banner."""
    source_names = ", ".join(source.name for source in sources)
    console.print(f"Running {duration_s}s telemetry test...")
    console.print(f"  Run ID: [bold]{run_id}[/bold]")
    console.print(f"  Sources: {source_names}")
    if skipped_sources:
        console.print(f"  Skipped: {', '.join(skipped_sources)}")


async def _wait_for_duration(
    *,
    duration_s: int,
    orchestrator: TelemetryOrchestrator,
    quiet: bool,
    interrupt_event: asyncio.Event,
) -> None:
    """Wait for duration while printing periodic source counts."""
    start = time.monotonic()
    next_tick = PROGRESS_INTERVAL_S
    while True:
        elapsed = time.monotonic() - start
        remaining = duration_s - elapsed
        if remaining <= 0:
            break

        sleep_for = min(remaining, max(0.1, next_tick - elapsed))
        with suppress(TimeoutError):
            await asyncio.wait_for(interrupt_event.wait(), timeout=sleep_for)
        if interrupt_event.is_set():
            break
        elapsed = time.monotonic() - start
        if not quiet and elapsed >= next_tick and elapsed < duration_s:
            counts = ", ".join(
                f"{source}={count}"
                for source, count in sorted(orchestrator.state.samples_per_source.items())
            )
            console.print(f"  [{elapsed:.0f}s] Samples received: {counts or 'none yet'}")
            next_tick += PROGRESS_INTERVAL_S


def _install_sigint_handler(interrupt_event: asyncio.Event) -> Callable[[], None]:
    """Install an event-loop SIGINT handler and return a restore callback."""
    loop = asyncio.get_running_loop()
    previous_handler = signal.getsignal(signal.SIGINT)
    try:
        loop.add_signal_handler(signal.SIGINT, interrupt_event.set)
    except (NotImplementedError, RuntimeError):
        return lambda: None

    def _restore() -> None:
        loop.remove_signal_handler(signal.SIGINT)
        signal.signal(signal.SIGINT, previous_handler)

    return _restore


def _finish_run(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
    status: str,
) -> None:
    """Mark the telemetry test run complete."""
    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            msg = f"run row disappeared before finish: {run_id}"
            raise RuntimeError(msg)
        run.status = status
        run.finished_at = dt.datetime.now(dt.UTC)
        session.commit()


def _build_summary(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
    duration_s: float,
    expected_sources: Sequence[str],
    skipped_sources: Sequence[str],
) -> TelemetryTestSummary:
    """Build a post-run summary from persisted telemetry rows."""
    metric_counts: dict[str, dict[str, int]] = defaultdict(dict)
    with session_factory() as session:
        rows = session.execute(
            select(TelemetrySampleRow.source, TelemetrySampleRow.metric, func.count())
            .where(TelemetrySampleRow.run_id == run_id)
            .group_by(TelemetrySampleRow.source, TelemetrySampleRow.metric),
        )
        for source, metric, count in rows:
            metric_counts[str(source)][str(metric)] = int(count)

        run = session.get(Run, run_id)
        if run is None:
            msg = f"run row not found for summary: {run_id}"
            raise RuntimeError(msg)
        partial = run.telemetry_partial
        partial_sources = list(run.telemetry_partial_sources or [])

    source_summaries = []
    for source in expected_sources:
        counts = metric_counts.get(source, {})
        samples = max(counts.values(), default=0)
        row_count = sum(counts.values())
        status = "PARTIAL" if source in partial_sources else "OK"
        source_summaries.append(
            SourceSummary(
                source=source,
                samples=samples,
                rows=row_count,
                rate_hz=samples / duration_s if duration_s > 0 else 0.0,
                status=status,
            ),
        )

    return TelemetryTestSummary(
        run_id=run_id,
        duration_s=duration_s,
        telemetry_partial=partial,
        telemetry_partial_sources=partial_sources,
        sources=source_summaries,
        skipped_sources=list(skipped_sources),
    )


def _print_summary(summary: TelemetryTestSummary, *, output_format: OutputFormat) -> None:
    """Print a summary in the selected format."""
    if output_format == "json":
        click.echo(json.dumps(_summary_as_dict(summary), sort_keys=True))
        return

    if output_format == "csv":
        click.echo(_summary_as_csv(summary))
        return

    table = Table(title="Telemetry Test Summary", show_lines=False, header_style="bold")
    table.add_column("Source")
    table.add_column("Samples", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Rate (Hz)", justify="right")
    table.add_column("Status")
    for source in summary.sources:
        table.add_row(
            source.source,
            str(source.samples),
            str(source.rows),
            f"{source.rate_hz:.1f}",
            source.status,
        )

    console.print()
    console.print(table)
    console.print(
        f"Run ID: [bold]{summary.run_id}[/bold] - Duration: {summary.duration_s:.2f}s - "
        f"telemetry_partial: [bold]{summary.telemetry_partial}[/bold]",
    )
    if summary.skipped_sources:
        console.print(f"Skipped sources: {', '.join(summary.skipped_sources)}")


def _summary_as_dict(summary: TelemetryTestSummary) -> dict[str, object]:
    return {
        "run_id": summary.run_id,
        "duration_s": summary.duration_s,
        "telemetry_partial": summary.telemetry_partial,
        "telemetry_partial_sources": summary.telemetry_partial_sources,
        "skipped_sources": summary.skipped_sources,
        "sources": [
            {
                "source": source.source,
                "samples": source.samples,
                "rows": source.rows,
                "rate_hz": source.rate_hz,
                "status": source.status,
            }
            for source in summary.sources
        ],
    }


def _summary_as_csv(summary: TelemetryTestSummary) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=("run_id", "source", "samples", "rows", "rate_hz", "status"),
    )
    writer.writeheader()
    for source in summary.sources:
        writer.writerow(
            {
                "run_id": summary.run_id,
                "source": source.source,
                "samples": source.samples,
                "rows": source.rows,
                "rate_hz": f"{source.rate_hz:.3f}",
                "status": source.status,
            },
        )
    return output.getvalue().strip()


def _build_configured_sources() -> list[TelemetrySource]:
    """Return telemetry sources visible to the CLI."""
    if _env_flag(REAL_TELEMETRY_ENV) or _env_flag(REAL_I2C_ENV):
        return [
            Ina219Source(Ina219Config(address=_env_i2c_address(INA219_ADDRESS_ENV, 0x40))),
            Bme280Source(Bme280Config(address=_env_i2c_address(BME280_ADDRESS_ENV, 0x77))),
        ]
    return [MockTelemetrySource()]


def _env_flag(name: str) -> bool:
    """Return True when an environment flag is set to a truthy value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_i2c_address(name: str, default: int) -> int:
    """Read an I2C address from an environment variable."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw, 0)
    except ValueError as exc:
        msg = f"{name} must be an integer I2C address such as 0x40, got {raw!r}"
        raise ValueError(msg) from exc


def _fnb58_transport() -> str:
    """Return the configured FNB58 transport."""
    transport = os.environ.get(FNB58_TRANSPORT_ENV, FNB58_TRANSPORT_BLE).strip().lower()
    if transport not in FNB58_TRANSPORT_CHOICES:
        choices = ", ".join(sorted(FNB58_TRANSPORT_CHOICES))
        msg = f"{FNB58_TRANSPORT_ENV} must be one of: {choices}"
        raise ValueError(msg)
    return transport


def _source_library_label(source: TelemetrySource) -> str:
    if isinstance(source, Ina219Source):
        return "adafruit-circuitpython-ina219"
    if isinstance(source, Bme280Source):
        return "adafruit-circuitpython-bme280"
    if isinstance(source, FnirsiHidSource):
        return "hidapi"
    if isinstance(source, FnirsiSource):
        return "bleak"
    return "-"


def _source_hardware_label(source: TelemetrySource) -> str:
    if isinstance(source, Ina219Source):
        return "INA219 over Blinka I2C"
    if isinstance(source, Bme280Source):
        return "BME280 over Blinka I2C"
    if isinstance(source, FnirsiHidSource):
        return "FNIRSI FNB58 USB-HID"
    if isinstance(source, FnirsiSource):
        return "FNIRSI FNB58 BLE"
    return "synthetic"


def _ensure_database(db_path: Path) -> None:
    """Create or upgrade the SQLite database for telemetry smoke tests."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _create_test_run(
    session_factory: sessionmaker[Session],
    *,
    duration_s: int,
    source_names: Sequence[str],
    skipped_sources: Sequence[str],
    fnb58_enabled: bool,
) -> str:
    """Create a telemetry-test run row with minimal target/task FK rows."""
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(
                Target.name == "telemetry-test",
                Target.kind == "telemetry_test",
            ),
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name="telemetry-test",
                kind="telemetry_test",
            )
            session.add(target)

        task = session.scalar(
            select(Task).where(
                Task.name == "telemetry-test",
                Task.version == "1",
            ),
        )
        if task is None:
            task = Task(
                task_id=new_id(),
                name="telemetry-test",
                version="1",
                family="telemetry",
            )
            session.add(task)

        session.flush()
        run = Run(
            run_id=new_id(),
            target_id=target.target_id,
            task_id=task.task_id,
            started_at=dt.datetime.now(dt.UTC),
            status="running",
            corpus_tag="X",
            warmup_count=0,
            measurement_count=0,
            signal_bench_version=__version__,
            runtime_name="signal-bench-cli",
            runtime_version=__version__,
            telemetry_partial=False,
            telemetry_partial_sources=None,
            extra={
                "kind": "telemetry_test",
                "duration_seconds": duration_s,
                "sources": list(source_names),
                "skipped_sources": list(skipped_sources),
                "fnb58_enabled": fnb58_enabled,
            },
        )
        session.add(run)
        session.commit()
        return run.run_id
