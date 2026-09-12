# SPDX-License-Identifier: Apache-2.0
"""Run and aggregate MCU repeatability energy sessions for A03.

Measurement mode delegates the hardware-facing build/flash/measure work to
``scripts/run_p3_mcu_matrix.py`` so the repeatability sessions use the same
firmware staging and telemetry path as the completed Session 1 curve. New runs
are tagged in ``runs.extra.session_label`` after each cell completes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import subprocess
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "p3_mcu_matrix.db"
RESULTS_PATH = ROOT / "results" / "repeatability_stats.json"
P3_RUNNER = ROOT / "scripts" / "run_p3_mcu_matrix.py"
TARGETS = ("esp32s3", "nano33", "f401re")
TASKS = ("kws", "ic", "ad")


def main() -> int:
    """Run a repeatability session or aggregate existing sessions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--session-label")
    parser.add_argument(
        "--power-boundary",
        help="Required for measurement runs: operator-recorded power boundary and meter placement.",
    )
    parser.add_argument("--targets", nargs="+", default=["all-mcu"])
    parser.add_argument("--tasks", nargs="+", choices=TASKS)
    parser.add_argument("--port", action="append", default=[], metavar="TARGET=PORT")
    parser.add_argument("--measurement-s", type=float, default=32.0)
    parser.add_argument("--sample-count", type=int, default=12)
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--sessions", default="session_1,session_2,session_3")
    parser.add_argument("--results-json", type=Path, default=RESULTS_PATH)
    args = parser.parse_args()

    if args.aggregate:
        sessions = [item.strip() for item in args.sessions.split(",") if item.strip()]
        stats = aggregate_sessions(args.db, sessions)
        args.results_json.parent.mkdir(parents=True, exist_ok=True)
        args.results_json.write_text(
            json.dumps(stats, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(stats, indent=2, sort_keys=True))
        return 0

    if not args.session_label:
        parser.error("--session-label is required unless --aggregate is used")

    cells = _cells(args.db, args.targets, args.tasks)
    summaries: list[dict[str, Any]] = []
    for target, task in cells:
        before = _run_ids(args.db)
        command = [
            sys.executable,
            str(P3_RUNNER),
            "--db",
            str(args.db),
            "--targets",
            target,
            "--tasks",
            task,
            "--no-fnb58",
            "--measurement-s",
            str(args.measurement_s),
            "--sample-count",
            str(args.sample_count),
            "--power-boundary",
            args.power_boundary or "",
        ]
        for override in args.port:
            command.extend(["--port", override])
        subprocess.run(command, check=True)
        new_run_ids = sorted(_run_ids(args.db) - before)
        if not new_run_ids:
            raise SystemExit(f"no new run recorded for {target}/{task}")
        run_id = new_run_ids[-1]
        _tag_session(args.db, run_id, args.session_label)
        summary = _run_summary(args.db, run_id, args.session_label)
        if summary["telemetry_partial"]:
            raise SystemExit(f"telemetry partial for {target}/{task}: {summary}")
        summaries.append(summary)
        print(json.dumps(summary, sort_keys=True))

    sessions = ["session_1", args.session_label]
    stats = aggregate_sessions(args.db, sessions)
    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def aggregate_sessions(db_path: Path, session_labels: list[str]) -> dict[str, Any]:
    """Aggregate Wh/1000 by target/task across requested sessions."""
    cells: dict[tuple[str, str], dict[str, float]] = {}
    for session_label in session_labels:
        for row in _latest_runs_for_session(db_path, session_label):
            key = (row["target"], row["task"])
            cells.setdefault(key, {})[session_label] = row["wh_per_1000"]

    payload = {
        "generated": dt.datetime.now(dt.UTC).isoformat(),
        "actions": ["A03"],
        "sessions": session_labels,
        "cells": [],
    }
    for target, task in sorted(cells):
        by_session = cells[(target, task)]
        values = [by_session[label] for label in session_labels if label in by_session]
        payload["cells"].append(
            {
                "target": target,
                "task": task,
                "wh_per_1000_mean": statistics.fmean(values) if values else None,
                "wh_per_1000_std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "wh_per_1000_by_session": [by_session.get(label) for label in session_labels],
                "session_count": len(values),
            }
        )
    return payload


def _cells(db_path: Path, targets: list[str], tasks: list[str] | None) -> list[tuple[str, str]]:
    target_filter = TARGETS if targets == ["all-mcu"] else tuple(targets)
    task_filter = TASKS if tasks is None else tuple(tasks)
    discovered = _accepted_session1_cells(db_path)
    if discovered:
        return [
            (target, task)
            for target, task in discovered
            if target in target_filter and task in task_filter
        ]
    return [(target, task) for target in target_filter for task in task_filter]


def _accepted_session1_cells(db_path: Path) -> list[tuple[str, str]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            """
            SELECT DISTINCT targets.name, tasks.name
            FROM runs
            JOIN targets ON targets.target_id = runs.target_id
            JOIN tasks ON tasks.task_id = runs.task_id
            WHERE targets.kind = 'mcu'
              AND runs.status = 'completed'
              AND runs.telemetry_partial = 0
              AND runs.corpus_tag = 'N3'
            ORDER BY targets.name, tasks.name
            """
        ).fetchall()
    return [(str(target), str(task)) for target, task in rows]


def _latest_runs_for_session(db_path: Path, session_label: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        if session_label == "session_1":
            rows = db.execute(
                """
                SELECT runs.run_id, targets.name AS target, tasks.name AS task, runs.started_at
                FROM runs
                JOIN targets ON targets.target_id = runs.target_id
                JOIN tasks ON tasks.task_id = runs.task_id
                WHERE targets.kind = 'mcu'
                  AND runs.status = 'completed'
                  AND runs.telemetry_partial = 0
                  AND runs.corpus_tag = 'N3'
                  AND COALESCE(json_extract(runs.extra, '$.energy_quarantined'), 0) = 0
                  AND COALESCE(json_extract(runs.extra, '$.repeat_quarantined'), 0) = 0
                  AND json_extract(runs.extra, '$.protocol') = 'n3'
                  AND json_extract(runs.extra, '$.session_label') IS NULL
                ORDER BY runs.started_at
                """
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT runs.run_id, targets.name AS target, tasks.name AS task, runs.started_at
                FROM runs
                JOIN targets ON targets.target_id = runs.target_id
                JOIN tasks ON tasks.task_id = runs.task_id
                WHERE targets.kind = 'mcu'
                  AND runs.status = 'completed'
                  AND runs.telemetry_partial = 0
                  AND runs.corpus_tag = 'N3'
                  AND COALESCE(json_extract(runs.extra, '$.energy_quarantined'), 0) = 0
                  AND COALESCE(json_extract(runs.extra, '$.repeat_quarantined'), 0) = 0
                  AND json_extract(runs.extra, '$.protocol') = 'n3'
                  AND json_extract(runs.extra, '$.session_label') = ?
                ORDER BY runs.started_at
                """,
                (session_label,),
            ).fetchall()
    latest: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        latest[(str(row["target"]), str(row["task"]))] = row
    return [
        {
            "target": str(row["target"]),
            "task": str(row["task"]),
            "run_id": str(row["run_id"]),
            "wh_per_1000": _wh_per_1000(db_path, str(row["run_id"])),
        }
        for row in latest.values()
    ]


def _run_ids(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT run_id FROM runs").fetchall()
    return {str(row[0]) for row in rows}


def _tag_session(db_path: Path, run_id: str, session_label: str) -> None:
    with sqlite3.connect(db_path) as db:
        row = db.execute("SELECT extra FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        extra = json.loads(row[0]) if row and row[0] else {}
        extra["session_label"] = session_label
        extra["session_tagged_at"] = dt.datetime.now(dt.UTC).isoformat()
        db.execute(
            "UPDATE runs SET extra = ? WHERE run_id = ?",
            (json.dumps(extra, sort_keys=True), run_id),
        )
        db.commit()


def _run_summary(db_path: Path, run_id: str, session_label: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            """
            SELECT targets.name AS target, tasks.name AS task, runs.measurement_count,
                   runs.telemetry_partial
            FROM runs
            JOIN targets ON targets.target_id = runs.target_id
            JOIN tasks ON tasks.task_id = runs.task_id
            WHERE runs.run_id = ?
            """,
            (run_id,),
        ).fetchone()
    return {
        "session_label": session_label,
        "run_id": run_id,
        "target": str(row["target"]),
        "task": str(row["task"]),
        "measurement_count": int(row["measurement_count"]),
        "telemetry_partial": bool(row["telemetry_partial"]),
        "wh_per_1000": _wh_per_1000(db_path, run_id),
    }


def _wh_per_1000(db_path: Path, run_id: str) -> float | None:
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            """
            SELECT timestamp, value
            FROM telemetry_samples
            WHERE run_id = ? AND source = 'ina219' AND metric = 'power'
            ORDER BY timestamp
            """,
            (run_id,),
        ).fetchall()
        count_row = db.execute(
            "SELECT measurement_count FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    inference_count = int(count_row[0]) if count_row else 0
    if len(rows) < 2 or inference_count <= 0:
        return None
    joules = 0.0
    parsed = [(_parse_timestamp(str(timestamp)), float(value)) for timestamp, value in rows]
    for previous, current in pairwise(parsed):
        dt_s = (current[0] - previous[0]).total_seconds()
        if dt_s > 0:
            joules += ((previous[1] + current[1]) / 2.0) * dt_s
    return joules / 3600.0 / inference_count * 1000.0


def _parse_timestamp(value: str) -> dt.datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
