#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run publication-grade Pi 5 CPU variance measurements."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import math
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SINGLE_RUN = ROOT / "scripts" / "run_phase1_pi5_ollama_live.py"
OUTPUT_ROOT = ROOT / "data" / "phase1" / "pi5-cpu"


def main() -> None:
    args = _parse_args()
    initial_throttle = _read_throttle(args)
    if args.require_clean_initial_throttle and initial_throttle["raw"] != "throttled=0x0":
        raise SystemExit(
            "Publication run requires a clean reboot before the suite; "
            f"got {initial_throttle['raw']}. Reboot the Pi and retry.",
        )

    run_id = f"phase1-pi5-cpu-publication-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_rows: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        throttle = _read_throttle(args)
        _abort_if_active_throttle(throttle, f"run {index}")
        if _has_historical_throttle(throttle):
            print(
                (
                    f"WARNING: publication run {index} starts with historical throttle bits "
                    f"set ({throttle['raw']}); recording and continuing because no active "
                    "throttle bits are set."
                ),
                file=sys.stderr,
                flush=True,
            )
        report_path = _run_single(args, index)
        row = _extract_row(index, report_path)
        row["throttle_start"] = throttle
        run_rows.append(row)

    aggregate = _aggregate(run_id, run_rows, initial_throttle)
    output_dir = OUTPUT_ROOT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "phase1-pi5-cpu-publication-report.json"
    md_path = output_dir / "phase1-pi5-cpu-publication-report.md"
    json_path.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(aggregate), encoding="utf-8")
    _write_latest_pointer(OUTPUT_ROOT / "latest-publication.json", json_path)
    print(f"Publication JSON: {json_path}")
    print(f"Publication Markdown: {md_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-host", default="<private-ip>")
    parser.add_argument(
        "--pi-user", default=os.environ.get("SIGNAL_BENCH_PI_USER", getpass.getuser())
    )
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--fnb58-address", default="<fnb58-address>")
    parser.add_argument(
        "--require-clean-initial-throttle", action=argparse.BooleanOptionalAction, default=True
    )
    return parser.parse_args()


def _run_single(args: argparse.Namespace, index: int) -> Path:
    env = os.environ.copy()
    command = [
        sys.executable,
        str(SINGLE_RUN),
        "--pi-host",
        args.pi_host,
        "--pi-user",
        args.pi_user,
        "--model",
        args.model,
        "--fnb58-address",
        args.fnb58_address,
    ]
    print(f"Starting Pi 5 publication run {index}/{args.runs}...", flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=2400,
    )
    print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"single-run command failed for run {index}: {completed.returncode}")
    match = re.search(r"^Report JSON:\s+(.+)$", completed.stdout, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"single-run output did not include report path for run {index}")
    return Path(match.group(1).strip())


def _extract_row(index: int, report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report["summary"]
    live = report["live_measurement"]
    return {
        "run_index": index,
        "run_id": report["run_id"],
        "report_path": str(report_path.relative_to(ROOT)),
        "tokens_per_second": summary["mean_tokens_per_second"],
        "ttft_ms": summary["median_first_token_ms"],
        "fnb58_joules_per_token": live["fnb58_wall_side"]["joules_per_token"],
        "ina219_joules_per_token": live["ina219_0x40_rail_side"]["joules_per_token"],
        "cross_check_relative_delta": report["measurement"]["cross_check"]["relative_delta"],
        "cross_check_flagged": report["measurement"]["cross_check"]["flagged"],
        "fnb58_avg_power_w": live["fnb58_wall_side"]["avg_power_w"],
        "ina219_avg_power_w": live["ina219_0x40_rail_side"]["avg_power_w"],
        "peak_memory_mb": summary["peak_memory_mb"],
        "accuracy_score": summary["accuracy_score"],
        "sample_rates_hz": live["sample_rates_hz"],
        "sample_rate_valid": live["sample_rate_validity"]["per_inference_valid"],
        "runtime": report["runtime"],
        "throttle_after": {
            "raw": live["pi_identity_after"]["throttled_before"],
            "decoded": live["pi_identity_after"]["throttled_before_decoded"],
        },
    }


def _aggregate(
    run_id: str,
    rows: list[dict[str, Any]],
    initial_throttle: dict[str, Any],
) -> dict[str, Any]:
    metrics = {
        "tokens_per_second": [row["tokens_per_second"] for row in rows],
        "ttft_ms": [row["ttft_ms"] for row in rows],
        "fnb58_joules_per_token": [row["fnb58_joules_per_token"] for row in rows],
        "ina219_joules_per_token": [row["ina219_joules_per_token"] for row in rows],
        "cross_check_relative_delta": [row["cross_check_relative_delta"] for row in rows],
    }
    metric_summaries = {name: _summarize(values) for name, values in metrics.items()}
    stability_gate = {
        name: summary["p99_over_p50"] < 1.4 if summary["p99_over_p50"] is not None else False
        for name, summary in metric_summaries.items()
    }
    return {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "target": "raspberry-pi-5-8gb",
        "backend": "pi5-cpu",
        "runtime": rows[0]["runtime"] if rows else None,
        "measurement_basis": "real_physical_meters",
        "energy_is_mock": False,
        "measurement_protocol": "warm_steady_state_v1",
        "supersedes": "data/phase1/pi5-cpu/phase1-pi5-cpu-20260611T043033Z/phase1-pi5-cpu-report.json",
        "energy_label_note": (
            "FNB58 measures USB cable delivery on the wall-side path. INA219 0x40 "
            "measures the Pi 5V system rail path. Both values are retained and "
            "labelled because a non-zero topology delta is expected."
        ),
        "run_count": len(rows),
        "initial_throttle": initial_throttle,
        "all_runs_no_active_throttle_at_start": all(
            not _has_active_throttle(row["throttle_start"]) for row in rows
        ),
        "all_runs_no_active_throttle_after_run": all(
            not _has_active_throttle(row["throttle_after"]) for row in rows
        ),
        "runs_with_historical_bits_at_start": [
            row["run_index"] for row in rows if _has_historical_throttle(row["throttle_start"])
        ],
        "runs_with_historical_bits_after_run": [
            row["run_index"] for row in rows if _has_historical_throttle(row["throttle_after"])
        ],
        "throttle_policy": (
            "Abort when lower active bits 0-3 are set. Historical upper bits 16-19 "
            "are recorded and warned on, but do not invalidate the run by themselves."
        ),
        "all_runs_sample_rate_valid": all(row["sample_rate_valid"] for row in rows),
        "any_cross_check_flagged": any(row["cross_check_flagged"] for row in rows),
        "metric_summaries": metric_summaries,
        "p99_over_p50_gate": {
            "threshold": 1.4,
            "per_metric": stability_gate,
            "passed": all(stability_gate.values()),
        },
        "runs": rows,
    }


def _summarize(values: list[float]) -> dict[str, float | None]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {
            "p50": None,
            "p99": None,
            "p99_over_p50": None,
            "mean": None,
            "stdev": None,
            "coefficient_of_variation": None,
            "min": None,
            "max": None,
        }
    p50 = statistics.median(clean)
    p99 = _nearest_rank_quantile(clean, 0.99)
    stdev = statistics.stdev(clean) if len(clean) > 1 else 0.0
    return {
        "p50": p50,
        "p99": p99,
        "p99_over_p50": p99 / p50 if p50 else None,
        "mean": statistics.fmean(clean),
        "stdev": stdev,
        "coefficient_of_variation": (
            stdev / statistics.fmean(clean) if statistics.fmean(clean) else None
        ),
        "min": min(clean),
        "max": max(clean),
    }


def _nearest_rank_quantile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _read_throttle(args: argparse.Namespace) -> dict[str, Any]:
    raw = _ssh_text(args, "vcgencmd get_throttled").strip()
    decoded = _decode_throttled(raw)
    return {"raw": raw, "decoded": decoded}


def _abort_if_active_throttle(throttle: dict[str, Any], label: str) -> None:
    if _has_active_throttle(throttle):
        raise SystemExit(f"Pi is actively throttled before {label}: {throttle['raw']}")


def _has_active_throttle(throttle: dict[str, Any]) -> bool:
    decoded = throttle["decoded"]
    return bool(
        decoded.get("active_under_voltage")
        or decoded.get("active_freq_capped")
        or decoded.get("active_throttled")
        or decoded.get("active_soft_temp_limit"),
    )


def _has_historical_throttle(throttle: dict[str, Any]) -> bool:
    decoded = throttle["decoded"]
    return bool(
        decoded.get("under_voltage_occurred_since_boot")
        or decoded.get("freq_capped_occurred_since_boot")
        or decoded.get("throttled_occurred_since_boot")
        or decoded.get("soft_temp_limit_occurred_since_boot"),
    )


def _decode_throttled(value: str) -> dict[str, Any]:
    _, _, raw = value.partition("=")
    try:
        flags = int(raw, 16)
    except ValueError:
        return {"raw": value, "decode_error": True}
    return {
        "raw": value,
        "active_under_voltage": bool(flags & 0x1),
        "active_freq_capped": bool(flags & 0x2),
        "active_throttled": bool(flags & 0x4),
        "active_soft_temp_limit": bool(flags & 0x8),
        "under_voltage_occurred_since_boot": bool(flags & 0x10000),
        "freq_capped_occurred_since_boot": bool(flags & 0x20000),
        "throttled_occurred_since_boot": bool(flags & 0x40000),
        "soft_temp_limit_occurred_since_boot": bool(flags & 0x80000),
    }


def _ssh_text(args: argparse.Namespace, remote_command: str) -> str:
    completed = subprocess.run(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{args.pi_user}@{args.pi_host}",
            remote_command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 1 Pi 5 CPU Publication-Grade Variance Report",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Target: `{report['target']}` / `{report['backend']}`",
        f"- Runtime: `{report['runtime']['runtime_name']}` `{report['runtime']['runtime_version']}`",
        f"- Model: `{report['runtime']['model_name']}`",
        f"- Model revision: `{report['runtime']['model_revision']}`",
        f"- Quantization: `{report['runtime']['quantization']}`",
        f"- Measurement basis: `{report['measurement_basis']}`",
        f"- Energy is mock: `{report['energy_is_mock']}`",
        f"- Energy labels: {report['energy_label_note']}",
        f"- Run count: `{report['run_count']}`",
        f"- Initial throttle register: `{report['initial_throttle']['raw']}`",
        f"- Throttle policy: {report['throttle_policy']}",
        f"- No active throttle at each run start: `{report['all_runs_no_active_throttle_at_start']}`",
        f"- No active throttle after each run: `{report['all_runs_no_active_throttle_after_run']}`",
        f"- Runs with historical bits at start: `{report['runs_with_historical_bits_at_start']}`",
        f"- Runs with historical bits after run: `{report['runs_with_historical_bits_after_run']}`",
        f"- Any cross-check flagged: `{report['any_cross_check_flagged']}`",
        f"- p99/p50 stability gate: `{report['p99_over_p50_gate']['passed']}` "
        f"(threshold `{report['p99_over_p50_gate']['threshold']}`)",
        "",
        "## Metric Summary",
        "",
        "| Metric | p50 | p99 | p99/p50 | mean | stdev | CV |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, summary in report["metric_summaries"].items():
        lines.append(
            f"| `{metric}` | {_fmt(summary['p50'])} | {_fmt(summary['p99'])} | "
            f"{_fmt(summary['p99_over_p50'])} | {_fmt(summary['mean'])} | "
            f"{_fmt(summary['stdev'])} | {_fmt(summary['coefficient_of_variation'])} |",
        )
    lines.extend(
        [
            "",
            "## Individual Runs",
            "",
            "| Run | tok/s | TTFT ms | FNB58 USB W | FNB58 J/token | INA219 rail W | INA219 J/token | Cross-check delta | Flagged | Throttle start | Report |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
        ],
    )
    for row in report["runs"]:
        lines.append(
            f"| {row['run_index']} | {row['tokens_per_second']:.3f} | "
            f"{row['ttft_ms']:.3f} | {row['fnb58_avg_power_w']:.6f} | "
            f"{row['fnb58_joules_per_token']:.6f} | "
            f"{row['ina219_avg_power_w']:.6f} | {row['ina219_joules_per_token']:.6f} | "
            f"{row['cross_check_relative_delta']:.6f} | "
            f"`{row['cross_check_flagged']}` | "
            f"`{row['throttle_start']['raw']} -> {row['throttle_after']['raw']}` | "
            f"`{row['report_path']}` |",
        )
    return "\n".join(lines).rstrip() + "\n"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}"


def _write_latest_pointer(pointer: Path, target: Path) -> None:
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps({"latest": str(target.relative_to(ROOT))}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
