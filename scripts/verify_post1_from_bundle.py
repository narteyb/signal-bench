# SPDX-License-Identifier: Apache-2.0
"""Fetch the pinned Post 1 telemetry bundle and verify launch figures."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path
from typing import Any

import generate_launch_tier_acceptance_bands as acceptance_bands
import yaml
from huggingface_hub import hf_hub_download
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from signal_bench.synth._partial import cell_headline
from signal_bench.synth.exporter import export_matrix
from signal_bench.synth.matrix_config import load_matrix_config
from signal_bench.synth.matrix_data import CellData, MatrixData, RunData

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_ID = "narteybrown/signal-bench-post1-telemetry-v1"
DEFAULT_REVISION = "08986c51ccb57c681a616524b10be31e7dd0d901"
DEFAULT_OUTPUT_DIR = ROOT / ".signal-bench-data" / "post1"
DEFAULT_MATRIX_CONFIG = ROOT / "configs" / "matrix.yaml"
DEFAULT_REFERENCE_MATRIX = ROOT / "data" / "matrices" / "post-1-data.yml"
DB_FILENAME = "p3_mcu_matrix.sanitized.sqlite"
RUN_INDEX_FILENAME = "run_index.csv"

CHECKS = (
    {
        "kind": "headline_latency_ms",
        "task": "kws",
        "target": "f401re",
        "label": "published median latency",
    },
    {
        "kind": "headline_energy_mwh_per_1000",
        "task": "kws",
        "target": "nano33",
        "label": "published Wh/1000 figure",
    },
    {
        "kind": "run_latency_variance_pct",
        "task": "ad",
        "target": "f401re",
        "run_id": "019f3676-d96e-7f10-9907-3586f4f15606",
        "label": "published variance figure",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--matrix-config", type=Path, default=DEFAULT_MATRIX_CONFIG)
    parser.add_argument("--reference-matrix", type=Path, default=DEFAULT_REFERENCE_MATRIX)
    parser.add_argument("--db", type=Path, help="Use an existing bundle DB instead of downloading.")
    parser.add_argument("--run-index", type=Path, help="Use an existing run_index.csv.")
    parser.add_argument("--run-id", help="Look up one run ID in the fetched bundle.")
    parser.add_argument("--power-source", default="ina219")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Require --db/--run-index and do not fetch from Hugging Face.",
    )
    args = parser.parse_args()

    if args.revision == "REPLACE_WITH_PINNED_DATASET_REVISION" and not args.db:
        raise SystemExit("dataset revision has not been pinned in this script yet")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = _resolve_bundle_paths(args)
    if args.run_id:
        _print_run_lookup(paths.run_index, args.run_id)
        return 0

    generated = _regenerate_matrix(paths.db, args)
    reference = _load_reference_matrix(args.reference_matrix)
    generated_path = args.output_dir / "post-1-data.regenerated.yml"
    generated_path.write_text(
        yaml.safe_dump(generated.to_dict(), sort_keys=False),
        encoding="utf-8",
    )

    bands_path = args.output_dir / "launch-tier-acceptance-bands.regenerated.md"
    bands_content = acceptance_bands.generate_markdown(
        argparse.Namespace(
            db=paths.db,
            matrix_config=args.matrix_config,
            output=bands_path,
            power_source=args.power_source,
        ),
    )
    bands_path.write_text(bands_content, encoding="utf-8")

    _verify_all_cited_runs_resolve(reference, paths.run_index)
    rows = _run_checks(generated, reference)
    _print_verification_report(args, paths, generated_path, bands_path, rows)
    return 0


class BundlePaths(argparse.Namespace):
    db: Path
    run_index: Path


def _resolve_bundle_paths(args: argparse.Namespace) -> BundlePaths:
    if args.skip_download and (not args.db or not args.run_index):
        raise SystemExit("--skip-download requires --db and --run-index")

    if args.db:
        db = args.db
    else:
        db = Path(
            hf_hub_download(
                args.repo_id,
                DB_FILENAME,
                repo_type="dataset",
                revision=args.revision,
                local_dir=args.output_dir,
                token=False,
            ),
        )
    if args.run_index:
        run_index = args.run_index
    else:
        run_index = Path(
            hf_hub_download(
                args.repo_id,
                RUN_INDEX_FILENAME,
                repo_type="dataset",
                revision=args.revision,
                local_dir=args.output_dir,
                token=False,
            ),
        )
    return BundlePaths(db=db, run_index=run_index)


def _regenerate_matrix(db_path: Path, args: argparse.Namespace) -> MatrixData:
    matrix_config = load_matrix_config(args.matrix_config)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            return export_matrix(
                matrix_config,
                session,
                output_path=None,
                power_source=args.power_source,
            )
    finally:
        engine.dispose()


def _load_reference_matrix(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _verify_all_cited_runs_resolve(reference: dict[str, Any], run_index_path: Path) -> None:
    cited = {
        run["run_id"]
        for cell in reference["cells"]
        for run in cell.get("runs", [])
        if run.get("run_id")
    }
    indexed = {row["run_id"] for row in _read_run_index(run_index_path)}
    missing = sorted(cited - indexed)
    if missing:
        raise RuntimeError(f"published run IDs missing from bundle index: {missing}")


def _read_run_index(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_checks(generated: MatrixData, reference: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check in CHECKS:
        generated_value = _check_value_generated(generated, check)
        reference_value = _check_value_reference(reference, check)
        rows.append(
            {
                "label": check["label"],
                "task": check["task"],
                "target": check["target"],
                "run_id": check.get("run_id"),
                "generated": generated_value,
                "published": reference_value,
                "match": _close(generated_value, reference_value),
            },
        )
    failed = [row for row in rows if not row["match"]]
    if failed:
        raise RuntimeError(f"verification checks failed: {failed}")
    return rows


def _check_value_generated(matrix: MatrixData, check: dict[str, Any]) -> float:
    cell = _generated_cell(matrix, check["task"], check["target"])
    if check["kind"] == "headline_latency_ms":
        value = cell_headline(cell.runs, "latency_ms")
    elif check["kind"] == "headline_energy_mwh_per_1000":
        value = cell_headline(cell.runs, "wh_per_1000_mwh")
    elif check["kind"] == "run_latency_variance_pct":
        run = _generated_run(cell, check["run_id"])
        value = None if run.latency_stats is None else run.latency_stats["variance_pct"]
    else:
        raise ValueError(f"unknown check kind: {check['kind']}")
    if value is None:
        raise RuntimeError(f"generated value unavailable for {check}")
    return float(value)


def _check_value_reference(reference: dict[str, Any], check: dict[str, Any]) -> float:
    cell = _reference_cell(reference, check["task"], check["target"])
    if check["kind"] == "headline_latency_ms":
        values = [
            float(run["latency_stats"]["median_us"]) / 1000.0
            for run in _eligible_reference_runs(cell)
            if run.get("latency_stats")
        ]
        return float(statistics.median(values))
    if check["kind"] == "headline_energy_mwh_per_1000":
        values = [
            float(run["energy_stats"]["wh_per_1000"]) * 1000.0
            for run in _eligible_reference_runs(cell)
            if run.get("energy_stats")
        ]
        return float(statistics.median(values))
    if check["kind"] == "run_latency_variance_pct":
        run = _reference_run(cell, check["run_id"])
        return float(run["latency_stats"]["variance_pct"])
    raise ValueError(f"unknown check kind: {check['kind']}")


def _eligible_reference_runs(cell: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        run
        for run in cell.get("runs", [])
        if not run.get("telemetry_partial")
        and not any(
            str(warning).startswith("repeat stats quarantined: ")
            for warning in run.get("warnings", [])
        )
    ]


def _generated_cell(matrix: MatrixData, task: str, target: str) -> CellData:
    for cell in matrix.cells:
        if cell.task == task and cell.target == target:
            return cell
    raise KeyError(f"generated cell not found: {task}/{target}")


def _reference_cell(reference: dict[str, Any], task: str, target: str) -> dict[str, Any]:
    for cell in reference["cells"]:
        if cell["task"] == task and cell["target"] == target:
            return cell
    raise KeyError(f"reference cell not found: {task}/{target}")


def _generated_run(cell: CellData, run_id: str) -> RunData:
    for run in cell.runs:
        if run.run_id == run_id:
            return run
    raise KeyError(f"generated run not found: {run_id}")


def _reference_run(cell: dict[str, Any], run_id: str) -> dict[str, Any]:
    for run in cell.get("runs", []):
        if run["run_id"] == run_id:
            return run
    raise KeyError(f"reference run not found: {run_id}")


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _print_run_lookup(run_index_path: Path, run_id: str) -> None:
    for row in _read_run_index(run_index_path):
        if row["run_id"] == run_id:
            print(f"Run ID: {row['run_id']}")
            print(f"Task/target: {row['task']}/{row['target']}")
            print(f"Started: {row['started_at']}")
            print(f"Raw artifact: {row['raw_artifact']}")
            print(f"Result rows: {row['result_rows']}")
            print(f"Telemetry rows: {row['telemetry_rows']}")
            print(f"Excluded from published tables: {row['excluded_from_published_tables']}")
            print(f"Exclusion reason: {row['exclusion_reason'] or 'none'}")
            return
    raise SystemExit(f"run ID not found in bundle index: {run_id}")


def _print_verification_report(
    args: argparse.Namespace,
    paths: BundlePaths,
    generated_path: Path,
    bands_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    print("Post 1 no-hardware verification succeeded.")
    print(f"Dataset: {args.repo_id}@{args.revision}")
    print(f"Raw DB: {paths.db}")
    print(f"Run index: {paths.run_index}")
    print(f"Regenerated matrix: {generated_path}")
    print(f"Regenerated acceptance bands: {bands_path}")
    print()
    print("| Check | Cell | Run ID | Regenerated | Published |")
    print("|---|---|---|---:|---:|")
    for row in rows:
        run_id = row["run_id"] or "-"
        print(
            f"| {row['label']} | {row['task']}/{row['target']} | {run_id} | "
            f"{row['generated']:.15g} | {row['published']:.15g} |",
        )
    print()
    print("All run IDs cited by the committed Post 1 matrix resolve in the bundle index.")
    print("Lookup example:")
    print(
        "  uv run python scripts/verify_post1_from_bundle.py "
        "--run-id 019e5da7-ef3e-7830-94a8-2ef6f6845b8e",
    )


if __name__ == "__main__":
    raise SystemExit(main())
