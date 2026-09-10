# SPDX-License-Identifier: Apache-2.0
"""Phase 1 SLM/VLM host-slice commands."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from signal_bench.ids import new_id
from signal_bench.phase1.adapters import host_runtime_adapter
from signal_bench.phase1.comparison import build_runtime_comparison, write_comparison_report
from signal_bench.phase1.harness import Phase1Harness, Phase1RunConfig
from signal_bench.phase1.report import summary_metrics

console = Console()


@click.group(name="phase1")
def phase1_group() -> None:
    """Run Phase 1 SLM/VLM harness slices."""


@phase1_group.command(name="host-slice")
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/phase1/host-slice/latest"),
    show_default=True,
)
@click.option("--model", default="qwen2.5:7b", show_default=True)
@click.option("--runtime", default="ollama", show_default=True)
def host_slice_cmd(output_dir: Path, model: str, runtime: str) -> None:
    """Run a real quantized SLM on the M1 Max with mock dual-meter telemetry."""
    repo_root = Path.cwd()
    runtime_adapter = None if runtime == "ollama" else host_runtime_adapter(runtime, model)
    report = Phase1Harness(
        Phase1RunConfig(
            repo_root=repo_root,
            output_dir=output_dir,
            model=model,
            runtime=runtime,
        ),
        runtime_adapter=runtime_adapter,
    ).run()
    summary = summary_metrics(report.results, report.measurement, report.accuracy)
    console.print(f"Phase 1 host slice complete: [bold]{report.run_id}[/bold]")
    console.print(f"Report JSON: {output_dir / 'phase1-host-slice-report.json'}")
    console.print(f"Report Markdown: {output_dir / 'phase1-host-slice-report.md'}")
    console.print(f"Mean tokens/s: {summary['mean_tokens_per_second']:.3f}")
    console.print(f"Joules/token: {summary['joules_per_token']:.6f}")
    console.print(f"Accuracy: {summary['accuracy_score']:.3f}")


@phase1_group.command(name="compare-host-runtimes")
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/phase1/host-runtime-comparison/latest"),
    show_default=True,
)
@click.option("--model", default="qwen2.5:7b", show_default=True)
@click.option(
    "--runtime",
    "runtimes",
    multiple=True,
    default=("ollama", "llama.cpp"),
    show_default=True,
)
def compare_host_runtimes_cmd(output_dir: Path, model: str, runtimes: tuple[str, ...]) -> None:
    """Run the same host workload across multiple runtimes and compare results."""
    repo_root = Path.cwd()
    reports = []
    for runtime in runtimes:
        runtime_output_dir = output_dir / _runtime_slug(runtime)
        runtime_adapter = host_runtime_adapter(runtime, model)
        report = Phase1Harness(
            Phase1RunConfig(
                repo_root=repo_root,
                output_dir=runtime_output_dir,
                model=model,
                runtime=runtime,
            ),
            runtime_adapter=runtime_adapter,
        ).run()
        reports.append((runtime, report, runtime_output_dir / "phase1-host-slice-report.json"))
    comparison = build_runtime_comparison(new_id(), tuple(reports))
    json_path, md_path = write_comparison_report(comparison, output_dir)
    console.print(
        f"Phase 1 host runtime comparison complete: [bold]{comparison.comparison_id}[/bold]",
    )
    console.print(f"Comparison JSON: {json_path}")
    console.print(f"Comparison Markdown: {md_path}")
    console.print("Energy basis: mock-dual-telemetry (not a physical measurement)")
    for row in comparison.rows:
        console.print(
            f"{row.runtime}: {row.mean_tokens_per_second:.3f} tok/s, "
            f"{row.median_first_token_ms:.3f} ms TTFT, "
            f"accuracy {row.accuracy_score:.3f}",
        )


def _runtime_slug(runtime: str) -> str:
    return runtime.casefold().replace(".", "-").replace("/", "-")
