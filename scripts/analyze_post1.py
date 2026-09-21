# SPDX-License-Identifier: Apache-2.0
"""Produce the descriptive Report 1 retrospective analysis.

The analysis unit is a completed N3 session named by the published-cell
manifest.  Selection is based on the recorded manifest and run metadata; no
measurement value is used to include or exclude a run.  The script reads the
canonical matrix database, the three retained scratch databases, and the
launch-tier reproduction database, derives
session-level latency and INA219 energy summaries, groups sessions by the
recorded measurement boundary, and writes deterministic Markdown reports.

Run with::

    uv run python scripts/analyze_post1.py

The default inputs are repository-relative so a fresh checkout can reproduce
the checked-in reports.  ``--check`` verifies the checked-in outputs without
rewriting them.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from signal_bench.synth.outlier import apply_outlier_policy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASES = (
    ROOT / "data/p3_mcu_matrix.db",
    ROOT / "data/scratch/p3_mcu_matrix.reference-scratch.20260524-215641.db",
    ROOT / "data/scratch/p3_mcu_matrix.esp-attempt.20260524-220230.db",
    ROOT / "data/scratch/p3_mcu_matrix.esp-pre-fnb-patch.20260524-220931.db",
    ROOT / "data/launch_tier_reproduction.db",
)
DEFAULT_SELECTION = ROOT / "content/signal-reports/2026-05-28-tinyml-reality-check-data.yml"
DEFAULT_OUTPUT = ROOT / "results/post1_retrospective"
TASKS = ("kws", "ic", "ad")
TARGETS = ("f401re", "nano33", "esp32s3")
BOUNDARY_ORDER = (
    "documented-full-board",
    "two-instrument-unrecorded",
    "single-instrument-unrecorded",
    "unknown-unrecorded",
)
CONFIDENCE_LEVEL = 0.95
INA219_SOURCE = "ina219"
POWER_METRIC = "power"
BME280_SOURCE = "bme280"


@dataclass(frozen=True, slots=True)
class Session:
    """One selected or excluded run with derived descriptive values."""

    database: str
    task: str
    target: str
    run_id: str
    started_at: str
    finished_at: str | None
    status: str
    corpus_tag: str
    protocol: str | None
    warmup_count: int
    measurement_count: int
    raw_result_count: int
    result_count: int
    latency_outlier_count: int
    latency_ms: float | None
    energy_wh_per_1000: float | None
    ambient_temperature_c: tuple[float, float] | None
    ambient_humidity_pct: tuple[float, float] | None
    boundary: str
    instrument_sources: tuple[str, ...]
    telemetry_partial: bool
    repeat_quarantined: bool
    energy_quarantined: bool
    session_label: str | None
    rerun_reason: str | None
    notes: str | None
    signal_bench_version: str
    runtime_name: str | None
    runtime_version: str | None
    model_hash: str | None
    quantization: str | None
    boundary_power: str | None
    boundary_meter: str | None
    extra_keys: tuple[str, ...]
    source_kind: str


@dataclass(frozen=True, slots=True)
class Cell:
    """The selected sessions for one task and target."""

    task: str
    target: str
    run_ids: tuple[str, ...]
    sessions: tuple[Session, ...]


@dataclass(frozen=True, slots=True)
class Comparison:
    """A descriptive ratio interval for one metric and boundary."""

    task: str
    metric: str
    target_a: str
    target_b: str
    boundary: str
    n_a: int
    n_b: int
    ratio: float
    lower: float
    upper: float
    degrees_of_freedom: float


def main() -> int:
    """Run the analysis and write or check its reports."""
    args = _parse_args()
    try:
        selected_ids = _load_selection(args.selection)
        records = _load_sessions(args.database)
        cells = _selected_cells(selected_ids, records)
        exclusions = _exclusions(selected_ids, records)
        outputs = _render_outputs(cells, exclusions, args.database, args.selection)
        if args.check:
            _check_outputs(args.output, outputs)
        else:
            args.output.mkdir(parents=True, exist_ok=True)
            for filename, content in outputs.items():
                (args.output / filename).write_text(content, encoding="utf-8")
        print(
            f"{'checked' if args.check else 'wrote'} {len(outputs)} reports in "
            f"{args.output.relative_to(ROOT)}",
        )
    except (OSError, RuntimeError, ValueError, sqlite3.Error, yaml.YAMLError) as exc:
        print(f"analysis failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        action="append",
        dest="database",
        default=None,
        help="SQLite run-record database; repeat for canonical, scratch, and launch-tier inputs.",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=DEFAULT_SELECTION,
        help="YAML file containing the published-cell run IDs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for generated reports.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare generated reports with existing files without writing.",
    )
    return parser.parse_args()


def _load_selection(path: Path) -> dict[tuple[str, str], tuple[str, ...]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    published_cells = _find_published_cells(payload)
    if len(published_cells) != 9:
        raise ValueError(f"expected 9 published cells, found {len(published_cells)}")
    selection: dict[tuple[str, str], tuple[str, ...]] = {}
    for cell in published_cells:
        task = str(cell.get("task"))
        target = str(cell.get("target"))
        run_ids = tuple(str(run_id) for run_id in cell.get("run_ids", ()))
        if task not in TASKS or target not in TARGETS:
            raise ValueError(f"unexpected published cell: {task}/{target}")
        if len(run_ids) != 3 or len(set(run_ids)) != 3:
            raise ValueError(f"{task}/{target} must contain exactly three unique run IDs")
        if (task, target) in selection:
            raise ValueError(f"duplicate published cell: {task}/{target}")
        selection[(task, target)] = run_ids
    expected = {(task, target) for task in TASKS for target in TARGETS}
    if set(selection) != expected:
        raise ValueError("published selection does not cover the 3-by-3 matrix")
    return selection


def _find_published_cells(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("published_cells")
        if isinstance(value, list):
            return value
        for child in payload.values():
            found = _find_published_cells(child)
            if found:
                return found
    elif isinstance(payload, list):
        for child in payload:
            found = _find_published_cells(child)
            if found:
                return found
    return []


def _load_sessions(paths: list[Path] | None) -> dict[str, Session]:
    databases = paths or list(DEFAULT_DATABASES)
    records: dict[str, Session] = {}
    for path in databases:
        if not path.exists():
            raise ValueError(f"run-record database does not exist: {path}")
        source_kind = "scratch" if "scratch" in path.parts else "canonical"
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                select r.*, t.name as task, g.name as target
                from runs r
                join tasks t on t.task_id = r.task_id
                join targets g on g.target_id = r.target_id
                order by t.name, g.name, r.started_at, r.run_id
                """,
            ).fetchall()
            for row in rows:
                session = _session_from_row(connection, row, path, source_kind)
                if session.run_id in records:
                    raise ValueError(f"run ID occurs in multiple databases: {session.run_id}")
                records[session.run_id] = session
    return records


def _session_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    path: Path,
    source_kind: str,
) -> Session:
    extra = _json_object(row["extra"])
    protocol = extra.get("protocol")
    instrument_sources = tuple(
        sorted(
            str(source)
            for source, in connection.execute(
                "select distinct source from telemetry_samples where run_id=?",
                (row["run_id"],),
            ).fetchall()
        )
    )
    result_rows = connection.execute(
        "select duration_ms from results where run_id=? order by sequence",
        (row["run_id"],),
    ).fetchall()
    measured = [float(result[0]) for result in result_rows][int(row["warmup_count"]) :]
    retained, outliers = apply_outlier_policy(measured, "iqr") if measured else ([], [])
    latency_ms = median(retained) if retained else None
    # The INA219 integral covers the whole measured run; IQR trimming is only
    # for latency statistics. Keep its normalization denominator on the same
    # post-warmup result set represented by that energy integral.
    energy = _energy_summary(connection, row, len(measured))
    ambient = _range_pair(connection, row["run_id"], BME280_SOURCE, "temperature")
    humidity = _range_pair(connection, row["run_id"], BME280_SOURCE, "humidity")
    return Session(
        database=str(path.relative_to(ROOT)),
        task=str(row["task"]),
        target=str(row["target"]),
        run_id=str(row["run_id"]),
        started_at=_utc_string(str(row["started_at"])),
        finished_at=(
            _utc_string(str(row["finished_at"])) if row["finished_at"] is not None else None
        ),
        status=str(row["status"]),
        corpus_tag=str(row["corpus_tag"]),
        protocol=str(protocol) if protocol is not None else None,
        warmup_count=int(row["warmup_count"]),
        measurement_count=int(row["measurement_count"]),
        raw_result_count=len(measured),
        result_count=len(retained),
        latency_outlier_count=len(outliers),
        latency_ms=latency_ms,
        energy_wh_per_1000=energy,
        ambient_temperature_c=ambient,
        ambient_humidity_pct=humidity,
        boundary=_boundary(extra, instrument_sources),
        instrument_sources=instrument_sources,
        telemetry_partial=bool(row["telemetry_partial"]),
        repeat_quarantined=bool(extra.get("repeat_quarantined")),
        energy_quarantined=bool(extra.get("energy_quarantined")),
        session_label=_optional_string(extra.get("session_label")),
        rerun_reason=_optional_string(extra.get("rerun_reason")),
        notes=_optional_string(row["notes"]),
        signal_bench_version=str(row["signal_bench_version"]),
        runtime_name=_optional_string(row["runtime_name"]),
        runtime_version=_optional_string(row["runtime_version"]),
        model_hash=_optional_string(row["model_hash"]),
        quantization=_optional_string(row["quantization"]),
        boundary_power=_optional_string((extra.get("boundary_state") or {}).get("power_boundary")),
        boundary_meter=_optional_string(
            (extra.get("boundary_state") or {}).get("authoritative_meter")
        ),
        extra_keys=tuple(sorted(extra)),
        source_kind=source_kind,
    )


def _energy_summary(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    inference_count: int,
) -> float | None:
    if inference_count == 0:
        return None
    samples = connection.execute(
        """
        select timestamp, value from telemetry_samples
        where run_id=? and source=? and metric=? order by timestamp
        """,
        (row["run_id"], INA219_SOURCE, POWER_METRIC),
    ).fetchall()
    if len(samples) < 2 or row["finished_at"] is None:
        return None
    started = _parse_timestamp(str(row["started_at"]))
    power_samples = [
        ((_parse_timestamp(str(timestamp)) - started).total_seconds(), float(value))
        for timestamp, value in samples
    ]
    total_j = sum(
        (power_a + power_b) / 2.0 * (time_b - time_a)
        for (time_a, power_a), (time_b, power_b) in pairwise(power_samples)
    )
    return total_j / 3600.0 / inference_count * 1000.0


def _range_pair(
    connection: sqlite3.Connection,
    run_id: str,
    source: str,
    metric: str,
) -> tuple[float, float] | None:
    values = [
        float(row[0])
        for row in connection.execute(
            "select value from telemetry_samples where run_id=? and source=? and metric=?",
            (run_id, source, metric),
        ).fetchall()
    ]
    return (min(values), max(values)) if values else None


def _boundary(extra: dict[str, Any], instrument_sources: tuple[str, ...]) -> str:
    if extra.get("boundary_state"):
        return "documented-full-board"
    power_sources = set(instrument_sources) & {"fnb58", "ina219"}
    if power_sources == {"fnb58", "ina219"}:
        return "two-instrument-unrecorded"
    if power_sources:
        return "single-instrument-unrecorded"
    return "unknown-unrecorded"


def _selected_cells(
    selection: dict[tuple[str, str], tuple[str, ...]],
    records: dict[str, Session],
) -> tuple[Cell, ...]:
    cells: list[Cell] = []
    for task in TASKS:
        for target in TARGETS:
            run_ids = selection[(task, target)]
            sessions = tuple(records[run_id] for run_id in run_ids if run_id in records)
            if len(sessions) != 3:
                missing = sorted(set(run_ids) - set(records))
                raise ValueError(f"missing selected runs for {task}/{target}: {missing}")
            cells.append(Cell(task, target, run_ids, sessions))
    return tuple(cells)


def _exclusions(
    selection: dict[tuple[str, str], tuple[str, ...]],
    records: dict[str, Session],
) -> tuple[tuple[Session, str], ...]:
    selected = {run_id for run_ids in selection.values() for run_id in run_ids}
    excluded: list[tuple[Session, str]] = []
    for session in records.values():
        if session.run_id in selected:
            continue
        reasons = _exclusion_reasons(session)
        excluded.append((session, "; ".join(reasons)))
    return tuple(
        sorted(excluded, key=lambda item: (item[0].task, item[0].target, item[0].started_at))
    )


def _exclusion_reasons(session: Session) -> list[str]:
    reasons: list[str] = []
    if session.source_kind == "scratch":
        reasons.append("preliminary scratch record")
    if session.corpus_tag != "N3" or session.protocol != "n3":
        reasons.append("different or unrecorded evaluation protocol")
    if session.status != "completed":
        reasons.append(f"recorded status={session.status}")
    if session.repeat_quarantined:
        reasons.append("recorded repeat quarantine")
    if session.telemetry_partial:
        reasons.append("recorded partial telemetry")
    if not reasons:
        reasons.append("outside the published three-session selection")
    return reasons


def _render_outputs(
    cells: tuple[Cell, ...],
    exclusions: tuple[tuple[Session, str], ...],
    databases: list[Path] | None,
    selection: Path,
) -> dict[str, str]:
    return {
        "session_table.md": _render_session_table(cells),
        "estimates.md": _render_estimates(cells),
        "findings.md": _render_findings(cells, exclusions, databases, selection),
    }


def _render_session_table(cells: tuple[Cell, ...]) -> str:
    lines = [
        "# Report 1 retrospective: session table",
        "",
        "Generated by `scripts/analyze_post1.py` from the published run selection.",
        "All timestamps are rendered as UTC. Latency is the median of retained measured results after the recorded warm-up count. Energy is INA219 trapezoidal energy normalized to Wh/1000 measured results.",
        "",
    ]
    for cell in cells:
        lines.extend(
            [
                f"## {cell.task.upper()} / {cell.target}",
                "",
                "| Run ID | Timestamp | Latency p50 (ms) | Energy (Wh/1000) | Ambient | Boundary | Protocol/status | Inferences (warm-up / measured) | Recorded conditions |",
                "|---|---|---:|---:|---|---|---|---:|---|",
            ]
        )
        for session in cell.sessions:
            lines.append(
                "| "
                + " | ".join(
                    (
                        f"`{session.run_id}`",
                        session.started_at,
                        _number(session.latency_ms),
                        _number(session.energy_wh_per_1000),
                        _ambient(session),
                        f"`{session.boundary}`",
                        f"{session.corpus_tag}/{session.protocol or 'not recorded'}; {session.status}; telemetry_partial={str(session.telemetry_partial).lower()}",
                        f"{session.warmup_count} / {session.raw_result_count} ({session.result_count} retained; {session.latency_outlier_count} IQR outliers)",
                        _conditions(session),
                    )
                )
                + " |",
            )
        lines.extend(["", "Boundary counts: " + _boundary_counts(cell.sessions) + ".", ""])
    return "\n".join(lines)


def _render_estimates(cells: tuple[Cell, ...]) -> str:
    comparisons = _comparisons(cells)
    lines = [
        "# Report 1 retrospective: descriptive estimates",
        "",
        "The preferred interval is a two-sided 95% Welch t-distribution interval on the log scale, centered on the log ratio of session medians. The degrees of freedom are the Welch-Satterthwaite value and are printed per row. The reported ratio is target A divided by target B; intervals are transformed back by exponentiation.",
        "",
        "The published three-session subset is not a random sample. These intervals, where eligible, describe these recorded sessions and do not establish a population-level claim.",
        "",
        "Bootstrap intervals are not used: with three observations per boundary group, percentile resampling is bounded by the observed values and is a poor uncertainty instrument for this design.",
        "",
        "## Eligible comparisons",
        "",
    ]
    if not comparisons:
        lines.extend(
            [
                "No comparison met the pre-specified boundary requirement: both cells must contribute at least three sessions with the same boundary state. No ratio or interval is therefore reported.",
                "",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "| Task | Metric | Target A | Target B | Boundary | n A | n B | Ratio | 95% interval | df |",
            "|---|---|---|---|---|---:|---:|---:|---|---:|",
        ]
    )
    for comparison in comparisons:
        lines.append(
            "| "
            + " | ".join(
                (
                    comparison.task.upper(),
                    comparison.metric,
                    comparison.target_a,
                    comparison.target_b,
                    f"`{comparison.boundary}`",
                    str(comparison.n_a),
                    str(comparison.n_b),
                    _number(comparison.ratio),
                    f"[{_number(comparison.lower)}, {_number(comparison.upper)}]",
                    _number(comparison.degrees_of_freedom),
                )
            )
            + " |",
        )
    return "\n".join(lines) + "\n"


def _render_findings(
    cells: tuple[Cell, ...],
    exclusions: tuple[tuple[Session, str], ...],
    databases: list[Path] | None,
    selection: Path,
) -> str:
    all_selected = [session for cell in cells for session in cell.sessions]
    boundary_counts = Counter(session.boundary for session in all_selected)
    cell_medians = {
        (cell.task, cell.target): (
            median([s.latency_ms for s in cell.sessions if s.latency_ms is not None]),
            median(
                [s.energy_wh_per_1000 for s in cell.sessions if s.energy_wh_per_1000 is not None]
            ),
        )
        for cell in cells
    }
    exclusion_counts = Counter(reason.split("; ")[0] for _, reason in exclusions)
    lines = [
        "# Report 1 retrospective findings",
        "",
        "## Executive finding",
        "",
        "The records support descriptive session-level reporting, not a cross-board energy conclusion at the strength of Report No. 1's wording. The published medians place Nano 33 below F401RE and ESP32-S3 on all three task rows, but the published sessions do not provide three boundary-matched sessions on both sides of any board comparison. The energy-winner statement is therefore an unadjusted description of the published medians, not a supported general claim that Nano 33 wins energy across every measured task.",
        "",
        "## Reproduction",
        "",
        f"The script is `scripts/analyze_post1.py`. It reads `{_relative_or_text(selection)}` and these run-record databases:",
        "",
    ]
    for path in databases or list(DEFAULT_DATABASES):
        lines.append(f"- `{_relative_or_text(path)}`")
    lines.extend(
        [
            "",
            "The deterministic command is `uv run python scripts/analyze_post1.py`; no random sampling or random seed is used. The generated files are `session_table.md`, `estimates.md`, and this document.",
            "",
            "## Exclusion rules",
            "",
            "Rules were fixed from recorded run metadata before deriving the estimates. No measured latency, energy, ambient value, or other numeric result is used as an exclusion condition.",
            "",
            "- A record from a scratch database is preliminary scratch provenance and is excluded from the published set.",
            "- A record whose corpus is not N3 or whose recorded protocol is not `n3` is excluded as a different or unrecorded evaluation protocol.",
            "- A record with a non-completed recorded status is excluded as failed or incomplete.",
            "- A record marked `repeat_quarantined` is excluded as a quarantined repeat.",
            "- A record marked `telemetry_partial` is excluded from the boundary-consistent published session set.",
            "- A completed N3 record that passes those checks but is not one of the three run IDs in the published-cell manifest is outside this retrospective's published subset.",
            "",
            "The selected 27 sessions are completed N3 records with no partial telemetry or repeat-quarantine marker. Excluded input records by primary reason are:",
            "",
            "| Primary reason | Records |",
            "|---|---:|",
        ]
    )
    for reason, count in sorted(exclusion_counts.items()):
        lines.append(f"| {reason} | {count} |")
    lines.extend(
        [
            "",
            "The complete excluded-record list is included below so the scope is auditable.",
            "",
            "| Cell/source | Run ID | Status | Reason |",
            "|---|---|---|---|",
        ]
    )
    for session, reason in exclusions:
        lines.append(
            f"| {session.task}/{session.target} ({session.source_kind}) | `{session.run_id}` | {session.status} | {reason} |",
        )
    lines.extend(
        [
            "",
            "## Boundary grouping",
            "",
            "The grouping is performed before any ratio calculation. A documented boundary is taken from `Run.extra.boundary_state`. When that field is absent, the retained power-source set distinguishes two-instrument capture from single-instrument capture, while preserving that the boundary itself was unrecorded.",
            "",
            "| Cell | Boundary counts | Estimate eligibility |",
            "|---|---|---|",
        ]
    )
    for cell in cells:
        counts = _boundary_counts(cell.sessions)
        eligible = (
            "at least three in one state"
            if any(
                count >= 3
                for count in Counter(session.boundary for session in cell.sessions).values()
            )
            else "description only for each state"
        )
        lines.append(f"| {cell.task}/{cell.target} | {counts} | {eligible} |")
    lines.extend(
        [
            "",
            f"Across the 27 selected sessions the boundary counts are {', '.join(f'`{key}`={boundary_counts[key]}' for key in BOUNDARY_ORDER if boundary_counts[key])}.",
            "",
            "Only matching boundary states can be compared. Because no pair of task cells has at least three sessions sharing the same boundary state, the estimates file contains no ratio rows. This is a design limitation, not evidence that board effects are absent.",
            "",
            "## Descriptive published medians",
            "",
            "These medians are shown to answer the Report No. 1 question directly. They combine the three published sessions in each cell exactly as Report No. 1 did; the boundary analysis above explains why they are not sufficient for the stronger cross-board claim.",
            "",
            "| Task | F401RE latency (ms) | Nano 33 latency (ms) | ESP32-S3 latency (ms) | F401RE energy (Wh/1000) | Nano 33 energy (Wh/1000) | ESP32-S3 energy (Wh/1000) |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for task in TASKS:
        values = [cell_medians[(task, target)] for target in TARGETS]
        lines.append(
            "| "
            + " | ".join(
                [
                    task.upper(),
                    *[_number(pair[0]) for pair in values],
                    *[_number(pair[1]) for pair in values],
                ]
            )
            + " |",
        )
    lines.extend(
        [
            "",
            "## What a session comprises",
            "",
            "For each selected run, the session value is the median of measured `results.duration_ms` rows after the recorded warm-up count, using the repository exporter's deterministic IQR policy. The table shows raw measured rows and retained rows. Energy is the trapezoidal INA219 integral across the measured run interval, normalized to 1,000 post-warmup result rows; IQR trimming applies to latency only. Per-inference energy attribution is not used. All selected sessions record zero warm-up rows in this database; the script still applies the stored warm-up count rather than assuming zero.",
            "",
            "The run records retain timestamps, result counts, corpus/protocol status, software version, runtime name/version, model hash, quantization, telemetry completeness, and selected boundary metadata. Ambient temperature and humidity ranges are taken from BME280 samples. They do not record a sitting identifier, cooldown/reset boundary between sessions, host version, compiler/toolchain version, or a complete per-session power-configuration record for the non-F401RE boards. Those fields remain unrecorded rather than being inferred.",
            "",
            "The run `extra` fields carry protocol, model lineage, session labels where assigned, rerun reasons where assigned, and boundary state where documented. No separate field identifies whether adjacent sessions belong to the same sitting, so timestamps are the available evidence for temporal spacing.",
            "",
            "## Limits of the finding",
            "",
            "The published subset is not a random sample. It supports reporting the recorded session values and the descriptive cell medians. It does not support a boundary-matched interval comparison across boards in this dataset, and it does not justify extending the Nano 33 energy ordering into a general claim across all measured tasks.",
            "",
        ]
    )
    return "\n".join(lines)


def _comparisons(cells: tuple[Cell, ...]) -> tuple[Comparison, ...]:
    by_key = {(cell.task, cell.target): cell for cell in cells}
    comparisons: list[Comparison] = []
    for task in TASKS:
        for index, target_a in enumerate(TARGETS):
            for target_b in TARGETS[index + 1 :]:
                cell_a = by_key[(task, target_a)]
                cell_b = by_key[(task, target_b)]
                states_a = defaultdict(list)
                states_b = defaultdict(list)
                for session in cell_a.sessions:
                    states_a[session.boundary].append(session)
                for session in cell_b.sessions:
                    states_b[session.boundary].append(session)
                for boundary in BOUNDARY_ORDER:
                    a = states_a.get(boundary, [])
                    b = states_b.get(boundary, [])
                    if len(a) < 3 or len(b) < 3:
                        continue
                    for metric, value_a, value_b in (
                        ("latency_ms", [s.latency_ms for s in a], [s.latency_ms for s in b]),
                        (
                            "energy_wh_per_1000",
                            [s.energy_wh_per_1000 for s in a],
                            [s.energy_wh_per_1000 for s in b],
                        ),
                    ):
                        if any(value is None or value <= 0 for value in (*value_a, *value_b)):
                            continue
                        comparisons.append(
                            _comparison(
                                task,
                                metric,
                                target_a,
                                target_b,
                                boundary,
                                [float(value) for value in value_a if value is not None],
                                [float(value) for value in value_b if value is not None],
                            )
                        )
    return tuple(comparisons)


def _comparison(
    task: str,
    metric: str,
    target_a: str,
    target_b: str,
    boundary: str,
    values_a: list[float],
    values_b: list[float],
) -> Comparison:
    logs_a = [math.log(value) for value in values_a]
    logs_b = [math.log(value) for value in values_b]
    ratio = math.exp(median(logs_a) - median(logs_b))
    variance_a = _sample_variance(logs_a)
    variance_b = _sample_variance(logs_b)
    standard_error = math.sqrt(variance_a / len(logs_a) + variance_b / len(logs_b))
    numerator = standard_error**4
    denominator = 0.0
    if variance_a:
        denominator += (variance_a / len(logs_a)) ** 2 / (len(logs_a) - 1)
    if variance_b:
        denominator += (variance_b / len(logs_b)) ** 2 / (len(logs_b) - 1)
    degrees_of_freedom = numerator / denominator if denominator else len(logs_a) + len(logs_b) - 2
    critical = _student_t_quantile(0.5 + CONFIDENCE_LEVEL / 2.0, degrees_of_freedom)
    log_ratio = math.log(ratio)
    margin = critical * standard_error
    return Comparison(
        task,
        metric,
        target_a,
        target_b,
        boundary,
        len(values_a),
        len(values_b),
        ratio,
        math.exp(log_ratio - margin),
        math.exp(log_ratio + margin),
        degrees_of_freedom,
    )


def _student_t_quantile(probability: float, degrees_of_freedom: float) -> float:
    """Invert the Student t CDF using the regularized incomplete beta."""
    if not 0.5 < probability < 1.0 or degrees_of_freedom <= 0:
        raise ValueError("invalid Student t quantile arguments")
    low, high = 0.0, 1.0
    while _student_t_cdf(high, degrees_of_freedom) < probability:
        high *= 2.0
    for _ in range(80):
        middle = (low + high) / 2.0
        if _student_t_cdf(middle, degrees_of_freedom) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _student_t_cdf(value: float, degrees_of_freedom: float) -> float:
    x = degrees_of_freedom / (degrees_of_freedom + value * value)
    beta = _regularized_beta(x, degrees_of_freedom / 2.0, 0.5)
    return 1.0 - beta / 2.0


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    factor = math.exp(a * math.log(x) + b * math.log1p(-x) - log_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return factor * _continued_fraction(x, a, b) / a
    return 1.0 - factor * _continued_fraction(1.0 - x, b, a) / b


def _continued_fraction(x: float, a: float, b: float) -> float:
    tiny = 1.0e-300
    maximum = 200
    epsilon = 3.0e-14
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = max(abs(d), tiny) * (1.0 if d >= 0 else -1.0)
    d = 1.0 / d
    h = d
    for index in range(1, maximum + 1):
        index_float = float(index)
        an = (
            index_float
            * (b - index_float)
            * x
            / ((qam + 2.0 * index_float) * (a + 2.0 * index_float))
        )
        d = 1.0 + an * d
        d = max(abs(d), tiny) * (1.0 if d >= 0 else -1.0)
        c = 1.0 + an / c
        c = max(abs(c), tiny) * (1.0 if c >= 0 else -1.0)
        d = 1.0 / d
        h *= d * c
        an = (
            -(a + index_float)
            * (qab + index_float)
            * x
            / ((a + 2.0 * index_float) * (qap + 2.0 * index_float))
        )
        d = 1.0 + an * d
        d = max(abs(d), tiny) * (1.0 if d >= 0 else -1.0)
        c = 1.0 + an / c
        c = max(abs(c), tiny) * (1.0 if c >= 0 else -1.0)
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return h


def _sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    center = sum(values) / len(values)
    return sum((value - center) ** 2 for value in values) / (len(values) - 1)


def _conditions(session: Session) -> str:
    software = f"signal-bench={session.signal_bench_version}"
    runtime = ", ".join(value for value in (session.runtime_name, session.runtime_version) if value)
    model = ", ".join(value for value in (session.model_hash, session.quantization) if value)
    power = session.boundary_power or "power configuration not recorded"
    changes = session.rerun_reason or session.notes or "no configuration change recorded"
    return "; ".join(
        (
            software,
            f"runtime={runtime or 'not recorded'}",
            f"model={model or 'not recorded'}",
            f"power={power}",
            "host/toolchain version not recorded",
            f"change={changes}",
        )
    ).replace("|", "/")


def _ambient(session: Session) -> str:
    temperature = _range_text(session.ambient_temperature_c, "°C")
    humidity = _range_text(session.ambient_humidity_pct, "%RH")
    return f"{temperature}; {humidity}"


def _range_text(value: tuple[float, float] | None, unit: str) -> str:
    if value is None:
        return f"{unit} not recorded"
    return f"{_number(value[0])}-{_number(value[1])} {unit}"


def _boundary_counts(sessions: tuple[Session, ...] | list[Session]) -> str:
    counts = Counter(session.boundary for session in sessions)
    return ", ".join(f"`{key}`={counts[key]}" for key in BOUNDARY_ORDER if counts[key])


def _number(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "not recorded"
    return f"{value:.9g}"


def _json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, dict) else {}


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None and str(value) else None


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_string(value: str) -> str:
    return _parse_timestamp(value).isoformat().replace("+00:00", "Z")


def _relative_or_text(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _check_outputs(output: Path, expected: dict[str, str]) -> None:
    mismatches = []
    for filename, content in expected.items():
        path = output / filename
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            mismatches.append(str(path))
    if mismatches:
        raise RuntimeError("generated output differs from: " + ", ".join(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
