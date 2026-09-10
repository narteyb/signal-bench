# SPDX-License-Identifier: Apache-2.0
"""`signal-bench synth`: report synthesis commands."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

import click
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from signal_bench.synth._partial import cell_detail
from signal_bench.synth.chart_data import write_chart_json_files
from signal_bench.synth.exporter import DEFAULT_OUTPUT_PATH, export_matrix
from signal_bench.synth.matrix_config import MatrixConfigError, load_matrix_config
from signal_bench.synth.report import cell_status, render_markdown_report, status_counts

if TYPE_CHECKING:
    from signal_bench.synth.matrix_data import MatrixData

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_INTERNAL_ERROR = 2
EXIT_CONFIG_ERROR = 3
EXIT_DB_ERROR = 4


class SynthCommandError(click.ClickException):
    """Click error with signal-bench synth exit code."""

    def __init__(self, message: str, exit_code: int) -> None:
        """Create a Click-compatible exception with a stable exit code."""
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class ReportOptions:
    """Resolved options for the synth report pipeline."""

    matrix_config_path: Path
    db_path: Path
    output_yaml: Path
    output_charts: Path
    output_report: Path
    skip_charts: bool
    skip_report: bool
    quiet: bool
    outlier_threshold: float
    power_source: str


@click.group(name="synth")
def synth_group() -> None:
    """Generate synthesis artifacts from benchmark measurements."""


@synth_group.command(name="report")
@click.option(
    "--matrix-config",
    "matrix_config_path",
    default=Path("configs/matrix.yaml"),
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to matrix-config YAML.",
)
@click.option(
    "--db",
    "db_path",
    default=Path("./signal-bench.db"),
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to SQLite benchmark database.",
)
@click.option(
    "--output-yaml",
    "output_yaml",
    default=DEFAULT_OUTPUT_PATH,
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to write matrix data YAML.",
)
@click.option(
    "--output-charts",
    "output_charts",
    default=Path("data/charts"),
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory for Chart.js JSON files.",
)
@click.option(
    "--output-report",
    "output_report",
    default=Path("data/reports/post-1-report.md"),
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to write markdown report.",
)
@click.option("--skip-charts", is_flag=True, help="Skip chart JSON generation.")
@click.option("--skip-report", is_flag=True, help="Skip markdown report generation.")
@click.option("--quiet", is_flag=True, help="Suppress progress output.")
@click.option(
    "--outlier-threshold",
    default=2.0,
    show_default=True,
    type=float,
    help="Report runs whose p95 latency exceeds this multiple of cell median latency.",
)
@click.option(
    "--power-source",
    default="fnb58",
    show_default=True,
    help="Telemetry source to use for exported energy statistics.",
)
def report_cmd(**kwargs: object) -> None:
    """Export matrix YAML, chart JSON, and a markdown synthesis report.

    Exit codes: 0 clean success, 1 completed with partial/incomplete cells,
    2 internal failure, 3 config error, 4 database error.
    """
    options = ReportOptions(
        matrix_config_path=cast("Path", kwargs["matrix_config_path"]),
        db_path=cast("Path", kwargs["db_path"]),
        output_yaml=cast("Path", kwargs["output_yaml"]),
        output_charts=cast("Path", kwargs["output_charts"]),
        output_report=cast("Path", kwargs["output_report"]),
        skip_charts=cast("bool", kwargs["skip_charts"]),
        skip_report=cast("bool", kwargs["skip_report"]),
        quiet=cast("bool", kwargs["quiet"]),
        outlier_threshold=cast("float", kwargs["outlier_threshold"]),
        power_source=cast("str", kwargs["power_source"]),
    )
    started = time.perf_counter()
    try:
        exit_code = _run_report_pipeline(options)
    except click.ClickException:
        raise
    except Exception as exc:
        message = f"Internal synth report failure: {exc}"
        raise SynthCommandError(message, EXIT_INTERNAL_ERROR) from exc

    if not options.quiet:
        elapsed = time.perf_counter() - started
        click.echo(f"Synth report complete in {elapsed:.2f}s.")
    raise click.exceptions.Exit(exit_code)


def _run_report_pipeline(options: ReportOptions) -> int:
    _validate_report_inputs(options)
    _echo(
        quiet=options.quiet,
        message=f"Loading matrix config from {options.matrix_config_path}...",
    )
    try:
        matrix_config = load_matrix_config(options.matrix_config_path)
    except MatrixConfigError as exc:
        _config_error(f"{exc}\nHint: fix the YAML schema or specify --matrix-config <path>.")
    _echo(
        quiet=options.quiet,
        message=(
            f"Loaded {len(matrix_config.cells)} cells across "
            f"{len(matrix_config.targets)} targets."
        ),
    )

    engine = create_engine(f"sqlite:///{options.db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        _echo(
            quiet=options.quiet,
            message=f"Exporting matrix data from {options.db_path}...",
        )
        with session_factory() as session:
            matrix_data = export_matrix(
                matrix_config,
                session,
                options.output_yaml,
                power_source=options.power_source,
            )
    except SQLAlchemyError as exc:
        _db_error(f"Database query failed for {options.db_path}: {exc}")
    finally:
        engine.dispose()

    _echo(
        quiet=options.quiet,
        message=f"Wrote matrix YAML to {options.output_yaml} ({_file_size(options.output_yaml)}).",
    )
    _emit_cell_summaries(matrix_data, quiet=options.quiet)

    chart_paths = {}
    if not options.skip_charts:
        _echo(
            quiet=options.quiet,
            message=f"Building chart JSON files in {options.output_charts}...",
        )
        chart_paths = write_chart_json_files(matrix_data, options.output_charts)
        if not options.quiet:
            for path in chart_paths.values():
                click.echo(f"  {path.name} ({_file_size(path)})")

    if not options.skip_report:
        _echo(
            quiet=options.quiet,
            message=f"Rendering markdown report to {options.output_report}...",
        )
        render_markdown_report(
            matrix_data,
            options.output_report,
            chart_dir=None if options.skip_charts else options.output_charts,
            outlier_threshold=options.outlier_threshold,
        )
        _echo(
            quiet=options.quiet,
            message=(
                f"Wrote markdown report to {options.output_report} "
                f"({_file_size(options.output_report)})."
            ),
        )

    counts = status_counts(matrix_data)
    summary = ", ".join(
        f"{status}={counts.get(status, 0)}" for status in ("OK", "NO_DATA", "PARTIAL", "INCOMPLETE")
    )
    click.echo(f"Status: {summary}")
    _emit_repeat_coverage_summary(matrix_data, quiet=options.quiet)
    _emit_partial_summary(matrix_data, quiet=options.quiet)
    return _report_exit_code(matrix_data)


def _validate_report_inputs(options: ReportOptions) -> None:
    if options.outlier_threshold <= 0:
        _config_error("--outlier-threshold must be positive.")
    if not options.matrix_config_path.exists():
        _config_error(
            f"Matrix config not found at {options.matrix_config_path}\n"
            "Hint: run T3.1 setup or specify --matrix-config <path>.",
        )
    if not options.db_path.exists():
        _db_error(
            f"Database file not accessible at {options.db_path}\n"
            "Hint: run signal-bench run to populate measurements, or specify --db <path>.",
        )


def _echo(*, quiet: bool, message: str) -> None:
    if not quiet:
        click.echo(message)


def _file_size(path: Path) -> str:
    return f"{path.stat().st_size / 1024:.1f}KB"


def _emit_cell_summaries(matrix_data: MatrixData, *, quiet: bool) -> None:
    if quiet:
        return
    for index, cell in enumerate(matrix_data.cells, start=1):
        detail = cell_detail(cell.runs)
        click.echo(
            f"  Cell {index}/{len(matrix_data.cells)}: "
            f"{cell.task}/{cell.target} - {len(cell.runs)} runs ({cell_status(cell)}), "
            f"partial={detail.n_partial}, headline_basis={detail.headline_basis}, "
            f"repeat_eligible={cell.eligible_run_count}/{cell.required_runs}, "
            f"missing={cell.missing_run_count}",
        )
        if cell.coverage_warnings:
            click.echo("    Coverage: " + "; ".join(cell.coverage_warnings))
        if detail.partial_inference_count:
            click.echo(
                "    Partial inference windows: "
                f"{detail.partial_inference_count} "
                f"({_partial_inference_source_summary(cell.runs)})",
            )


def _emit_partial_summary(matrix_data: MatrixData, *, quiet: bool) -> None:
    all_partial_cells: list[str] = []
    reason_sources: dict[str, int] = {}
    for cell in matrix_data.cells:
        detail = cell_detail(cell.runs)
        if detail.n_total and detail.headline_basis == 0:
            all_partial_cells.append(f"{cell.task}/{cell.target}")
        for run in cell.runs:
            for reason in run.partial_reasons:
                source = reason.split(":", 1)[0]
                reason_sources[source] = reason_sources.get(source, 0) + 1
    if all_partial_cells:
        click.echo(
            "Warning: headline values are null for all-partial cells: "
            + ", ".join(all_partial_cells),
        )
    if reason_sources and not quiet:
        summary = ", ".join(f"{source}={count}" for source, count in sorted(reason_sources.items()))
        click.echo(f"Partial reason sources: {summary}")


def _emit_repeat_coverage_summary(matrix_data: MatrixData, *, quiet: bool) -> None:
    missing_cells = [cell for cell in matrix_data.cells if cell.missing_run_count]
    required = sum(cell.required_runs for cell in matrix_data.cells)
    eligible = sum(cell.eligible_run_count for cell in matrix_data.cells)
    missing = sum(cell.missing_run_count for cell in matrix_data.cells)
    click.echo(f"Repeat coverage: eligible={eligible}/{required}, missing={missing}")
    if missing_cells:
        click.echo(
            "Warning: missing repeat runs: "
            + ", ".join(
                f"{cell.task}/{cell.target} missing {cell.missing_run_count}"
                for cell in missing_cells
            ),
        )
    if not quiet:
        extra_cells = [cell for cell in matrix_data.cells if cell.extra_run_count]
        if extra_cells:
            click.echo(
                "Extra repeat runs: "
                + ", ".join(
                    f"{cell.task}/{cell.target} extra {cell.extra_run_count}"
                    for cell in extra_cells
                ),
            )


def _report_exit_code(matrix_data: MatrixData) -> int:
    counts = status_counts(matrix_data)
    has_repeat_gap = any(cell.missing_run_count for cell in matrix_data.cells)
    if counts.get("PARTIAL", 0) or counts.get("INCOMPLETE", 0) or has_repeat_gap:
        return EXIT_WARNINGS
    return EXIT_OK


def _partial_inference_source_summary(runs) -> str:  # noqa: ANN001 - CLI formatting helper.
    counts: dict[str, int] = {}
    for run in runs:
        for warning in run.partial_inference_warnings:
            source = str(warning.get("source", "unknown"))
            counts[source] = counts.get(source, 0) + 1
    return ", ".join(f"{source}: {count}" for source, count in sorted(counts.items()))


def _config_error(message: str) -> NoReturn:
    raise SynthCommandError(message, EXIT_CONFIG_ERROR)


def _db_error(message: str) -> NoReturn:
    raise SynthCommandError(message, EXIT_DB_ERROR)
