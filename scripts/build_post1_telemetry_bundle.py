# SPDX-License-Identifier: Apache-2.0
"""Build the sanitized Post 1 telemetry bundle for Hugging Face publication."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from public_sanitizer import assert_clean_text, sanitize_json, sanitize_string

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = ROOT / "data" / "p3_mcu_matrix.db"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "post1-telemetry-bundle"
DEFAULT_CITED_ARTIFACTS = (
    ROOT / "content" / "signal-reports" / "2026-05-28-tinyml-reality-check-data.yml",
    ROOT / "data" / "matrices" / "post-1-data.yml",
    ROOT / "data" / "reports" / "post-1-report.md",
)
SANITIZED_DB_NAME = "p3_mcu_matrix.sanitized.sqlite"

RUN_ID_RE = re.compile(r"019[0-9a-f-]{33}")
JSON_SANITIZE_QUERIES = (
    (
        "run_id",
        "extra",
        "select run_id, extra from runs where extra is not null",
        "update runs set extra = ? where run_id = ?",
    ),
    (
        "failure_id",
        "toolchain_versions",
        "select failure_id, toolchain_versions from failures where toolchain_versions is not null",
        "update failures set toolchain_versions = ? where failure_id = ?",
    ),
    (
        "failure_id",
        "context",
        "select failure_id, context from failures where context is not null",
        "update failures set context = ? where failure_id = ?",
    ),
    (
        "failure_id",
        "extra",
        "select failure_id, extra from failures where extra is not null",
        "update failures set extra = ? where failure_id = ?",
    ),
)
TEXT_SANITIZE_QUERIES = (
    (
        "run_id",
        "notes",
        "select run_id, notes from runs where notes is not null",
        "update runs set notes = ? where run_id = ?",
    ),
    (
        "failure_id",
        "diagnostic_signature",
        "select failure_id, diagnostic_signature from failures where diagnostic_signature is not null",
        "update failures set diagnostic_signature = ? where failure_id = ?",
    ),
    (
        "failure_id",
        "error_log_uri",
        "select failure_id, error_log_uri from failures where error_log_uri is not null",
        "update failures set error_log_uri = ? where failure_id = ?",
    ),
    (
        "failure_id",
        "notes",
        "select failure_id, notes from failures where notes is not null",
        "update failures set notes = ? where failure_id = ?",
    ),
    (
        "target_id",
        "extra",
        "select target_id, extra from targets where extra is not null",
        "update targets set extra = ? where target_id = ?",
    ),
    (
        "task_id",
        "yaml_path",
        "select task_id, yaml_path from tasks where yaml_path is not null",
        "update tasks set yaml_path = ? where task_id = ?",
    ),
)
ROW_COUNT_QUERIES = {
    "runs": "select count(*) from runs",
    "results": "select count(*) from results",
    "telemetry_samples": "select count(*) from telemetry_samples",
    "failures": "select count(*) from failures",
    "targets": "select count(*) from targets",
    "tasks": "select count(*) from tasks",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--cited-artifact",
        action="append",
        type=Path,
        dest="cited_artifacts",
        help="Artifact containing launch-facing run IDs. May be repeated.",
    )
    args = parser.parse_args()

    cited_artifacts = tuple(args.cited_artifacts or DEFAULT_CITED_ARTIFACTS)
    output_dir = args.output_dir
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cited_run_ids = _published_run_ids(cited_artifacts)
    db_path = output_dir / SANITIZED_DB_NAME
    _copy_sqlite(args.source_db, db_path)
    _sanitize_database(db_path)
    _assert_clean(db_path)

    run_index = _write_run_index(db_path, cited_run_ids, output_dir)
    manifest = _write_manifest(
        source_db=args.source_db,
        sanitized_db=db_path,
        cited_artifacts=cited_artifacts,
        cited_run_ids=cited_run_ids,
        run_index=run_index,
        output_dir=output_dir,
    )
    _write_card(output_dir, manifest)
    print(f"Wrote sanitized Post 1 telemetry bundle to {output_dir}")
    print(f"Sanitized DB: {db_path}")
    print(f"Runs included: {manifest['row_counts']['runs']}")
    print(f"Published/cited run IDs resolved: {manifest['published_run_ids_resolved']}")
    return 0


def _published_run_ids(paths: tuple[Path, ...]) -> set[str]:
    run_ids: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        run_ids.update(RUN_ID_RE.findall(path.read_text(encoding="utf-8")))
    if not run_ids:
        raise RuntimeError("no cited Post 1 run IDs found")
    return run_ids


def _copy_sqlite(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    source_con = sqlite3.connect(source)
    try:
        dest_con = sqlite3.connect(destination)
        try:
            source_con.backup(dest_con)
            ok = dest_con.execute("pragma integrity_check").fetchone()[0]
            if ok != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {ok}")
        finally:
            dest_con.close()
    finally:
        source_con.close()


def _sanitize_database(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        for pk, column, select_query, update_query in JSON_SANITIZE_QUERIES:
            for row in con.execute(select_query):
                payload = json.loads(row[column])
                sanitized = sanitize_json(payload)
                con.execute(
                    update_query,
                    (json.dumps(sanitized, sort_keys=True), row[pk]),
                )
        for pk, column, select_query, update_query in TEXT_SANITIZE_QUERIES:
            for row in con.execute(select_query):
                con.execute(
                    update_query,
                    (sanitize_string(str(row[column])), row[pk]),
                )
        con.commit()
        con.execute("vacuum")
    finally:
        con.close()


def _assert_clean(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    try:
        dump = "\n".join(con.iterdump())
    finally:
        con.close()
    try:
        assert_clean_text(dump)
    except RuntimeError as exc:
        raise RuntimeError(f"sanitized DB still contains private patterns: {exc}") from exc


def _write_run_index(
    db_path: Path, cited_run_ids: set[str], output_dir: Path
) -> list[dict[str, Any]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows: list[dict[str, Any]] = []
    try:
        query = """
            select
                r.run_id,
                r.started_at,
                r.finished_at,
                r.status,
                r.warmup_count,
                r.measurement_count,
                r.telemetry_partial,
                r.telemetry_partial_sources,
                r.partial_reasons,
                r.corpus_tag,
                r.extra,
                t.name as target,
                k.name as task,
                (select count(*) from results rr where rr.run_id = r.run_id) as result_rows,
                (select count(*) from telemetry_samples ts where ts.run_id = r.run_id) as telemetry_rows
            from runs r
            join targets t on r.target_id = t.target_id
            join tasks k on r.task_id = k.task_id
            order by r.started_at, r.run_id
        """
        for row in con.execute(query):
            extra = json.loads(row["extra"] or "{}")
            repeat_reason = extra.get("repeat_quarantine_reason")
            energy_reason = extra.get("energy_quarantine_reason")
            rows.append(
                {
                    "run_id": row["run_id"],
                    "task": row["task"],
                    "target": row["target"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "status": row["status"],
                    "warmup_count": row["warmup_count"],
                    "measurement_count": row["measurement_count"],
                    "corpus_tag": row["corpus_tag"],
                    "result_rows": row["result_rows"],
                    "telemetry_rows": row["telemetry_rows"],
                    "telemetry_partial": bool(row["telemetry_partial"]),
                    "telemetry_partial_sources": _json_or_empty(row["telemetry_partial_sources"]),
                    "partial_reasons": _json_or_empty(row["partial_reasons"]),
                    "published_artifact_cited": row["run_id"] in cited_run_ids,
                    "excluded_from_published_tables": _excluded(
                        extra, bool(row["telemetry_partial"])
                    ),
                    "exclusion_reason": _exclusion_reason(extra, bool(row["telemetry_partial"])),
                    "energy_quarantined": bool(extra.get("energy_quarantined")),
                    "energy_quarantine_reason": energy_reason,
                    "repeat_quarantined": bool(extra.get("repeat_quarantined")),
                    "repeat_quarantine_reason": repeat_reason,
                    "raw_artifact": SANITIZED_DB_NAME,
                },
            )
    finally:
        con.close()
    _write_json(output_dir / "run_index.json", rows)
    with (output_dir / "run_index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _json_or_empty(value: str | None) -> Any:
    if not value:
        return []
    parsed = json.loads(value)
    return [] if parsed is None else parsed


def _excluded(extra: dict[str, Any], telemetry_partial: bool) -> bool:
    return bool(
        telemetry_partial
        or extra.get("energy_quarantined")
        or extra.get("repeat_quarantined")
        or extra.get("rejected_reason")
        or extra.get("rejected_attempt_reason")
    )


def _exclusion_reason(extra: dict[str, Any], telemetry_partial: bool) -> str | None:
    reasons: list[str] = []
    if telemetry_partial:
        reasons.append("telemetry partial")
    for key in (
        "energy_quarantine_reason",
        "repeat_quarantine_reason",
        "rejected_reason",
        "rejected_attempt_reason",
    ):
        if extra.get(key):
            reasons.append(str(extra[key]))
    return "; ".join(reasons) if reasons else None


def _write_manifest(
    *,
    source_db: Path,
    sanitized_db: Path,
    cited_artifacts: tuple[Path, ...],
    cited_run_ids: set[str],
    run_index: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    con = sqlite3.connect(sanitized_db)
    try:
        row_counts = {
            table: con.execute(query).fetchone()[0] for table, query in ROW_COUNT_QUERIES.items()
        }
    finally:
        con.close()
    indexed_run_ids = {row["run_id"] for row in run_index}
    missing = sorted(cited_run_ids - indexed_run_ids)
    if missing:
        raise RuntimeError(f"cited run IDs missing from sanitized DB: {missing}")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "data/p3_mcu_matrix.db",
        "source_sha256": _sha256(source_db),
        "files": {
            SANITIZED_DB_NAME: {"sha256": _sha256(sanitized_db)},
            "run_index.csv": {"sha256": _sha256(output_dir / "run_index.csv")},
            "run_index.json": {"sha256": _sha256(output_dir / "run_index.json")},
        },
        "row_counts": row_counts,
        "published_run_ids_cited": len(cited_run_ids),
        "published_run_ids_resolved": len(cited_run_ids),
        "full_db_runs_included": len(run_index),
        "cited_artifacts": [_display_path(path) for path in cited_artifacts if path.exists()],
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def _write_card(output_dir: Path, manifest: dict[str, Any]) -> None:
    card = f"""---
license: apache-2.0
pretty_name: Signal Bench Post 1 MCU Telemetry
tags:
- signal-bench
- tinyml
- energy-measurement
- telemetry
---

# Signal Bench Post 1 MCU Telemetry

This dataset publishes Dan Brown's raw launch-tier measurement telemetry for the
Post 1 TinyML MCU matrix in Signal Bench. It is measurement data produced by the
bench, not the third-party benchmark input datasets used by KWS, IC, or AD.

## Inventory

- `{SANITIZED_DB_NAME}`: sanitized SQLite database copied from the Post 1 source
  database, with all run rows, per-inference result rows, and telemetry samples.
- `run_index.csv` and `run_index.json`: lookup table from run ID to task, board,
  telemetry row counts, raw artifact, and exclusion/quarantine flags.
- `manifest.json`: checksums, row counts, and source artifact references.

The bundle includes the full Post 1 database contents: `{manifest['row_counts']['runs']}`
runs, `{manifest['row_counts']['results']}` result rows, and
`{manifest['row_counts']['telemetry_samples']}` telemetry samples. The
`{manifest['published_run_ids_cited']}` run IDs cited by the launch artifacts are
all present. Quarantined, superseded, rejected, and telemetry-partial rows are
retained for provenance and flagged in the run index rather than omitted.

## Measurement Boundary

Post 1 MCU energy uses the board-side INA219 as the authoritative power source.
The INA219 is wired high-side at the board 5 V input, upstream of the board
regulators. FNB58 wall-side measurements are retained as cross-check telemetry.
Ambient BME280 samples are included when captured.

## SQLite Tables

- `runs`: one benchmark run, including task, target, warmup count, measured count,
  corpus tag, telemetry-partial flags, and sanitized run metadata.
- `results`: per-inference latency, accuracy, and per-inference energy fields.
- `telemetry_samples`: timestamped meter and ambient samples keyed by run ID.
- `targets` and `tasks`: board and benchmark-task metadata.

Local filesystem paths and machine-layout details were sanitized from the
published copy. The measurements, timestamps, task/target labels, result rows,
telemetry samples, and quarantine flags are preserved.

## Exclusions

Rows excluded from published tables are still present. See
`excluded_from_published_tables` and `exclusion_reason` in `run_index.csv` or
`run_index.json`. Reasons include telemetry-partial windows, pre-discipline power
boundaries, superseded repeat sets, and rejected diagnostic attempts.

## License

The telemetry in this dataset is licensed Apache-2.0. This license covers Dan
Brown's measurement telemetry and generated provenance files in this bundle. It
does not relicense third-party benchmark input datasets or model training
corpora.
"""
    (output_dir / "README.md").write_text(card, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
