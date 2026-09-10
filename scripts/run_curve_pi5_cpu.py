# SPDX-License-Identifier: Apache-2.0
"""Run Curve Fan-Out Brief A Pi5 CPU X-corpus measurements.

Requires key-based SSH to ``--host``; this public script does not carry
password-based SSH credentials.
"""

# ruff: noqa: RUF007

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import math
import os
import shlex
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Result, Run, Target, Task, TelemetrySample
from signal_bench.telemetry.base import TelemetrySource
from signal_bench.telemetry.orchestrator import OrchestratorState, TelemetryOrchestrator
from signal_bench.telemetry.sources.bme280 import Bme280Config, Bme280Source
from signal_bench.telemetry.sources.fnirsi import FnirsiSource, FnirsiSourceConfig
from signal_bench.telemetry.sources.ina219 import Ina219Config, Ina219Source

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curve_fanout_briefA.db"
REPORT_PATH = ROOT / "reports" / "curve_fanout_briefA.md"
REMOTE_ROOT = "<remote-home>"
DEFAULT_HOST = "<ssh-user>@<private-ip>"
FNB58_ADDRESS = "<fnb58-address>"
SSH_OPTS = ["-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2"]


@dataclass(frozen=True, slots=True)
class Workload:
    task_id: str
    family: str
    version: str
    model: Path
    input_data: Path
    lineage_metric: str
    lineage_value: float
    parity_tolerance: float
    eval_note: str


@dataclass(frozen=True, slots=True)
class InferenceResult:
    sequence: int
    data_index: int
    timestamp: dt.datetime
    duration_us: int
    output: dict[str, Any]
    error: str | None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--remote-root", default=REMOTE_ROOT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--duration-s", type=float, default=35.0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--fnb58-address", default=FNB58_ADDRESS)
    parser.add_argument("--no-fnb58", action="store_true")
    parser.add_argument("--only", choices=["ic", "kws", "ad"], action="append")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


async def _main_async(args: argparse.Namespace) -> int:
    _configure_telemetry_env()
    _ensure_database(args.db)
    engine = create_engine(f"sqlite:///{args.db}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    r1 = _capture_r1(args.host)
    if "NO_HAILO_DEV" not in r1["hailo_device"]:
        raise RuntimeError(
            f"CPU-only card-out gate failed; /dev/hailo* is still present:\n{r1['hailo_device']}"
        )
    workloads = [item for item in _workloads() if not args.only or item.task_id in set(args.only)]
    _deploy_common(args.host, args.remote_root)
    summaries = []
    for workload in workloads:
        summary = await _run_workload(args, session_factory, workload, r1)
        summaries.append(summary)
        print(json.dumps({"task": workload.task_id, "summary": summary}, sort_keys=True))
    _write_report(args.report, r1, summaries)
    return 0


async def _run_workload(
    args: argparse.Namespace,
    session_factory: sessionmaker[Session],
    workload: Workload,
    r1: dict[str, str],
) -> dict[str, Any]:
    run_id = new_id()
    remote_task_root = f"{args.remote_root}/{workload.task_id}"
    remote_model = f"{remote_task_root}/{workload.model.name}"
    remote_input = f"{remote_task_root}/{workload.input_data.name}"
    remote_results = f"{remote_task_root}/{run_id}-results.jsonl"
    _remote_capture(args.host, f"mkdir -p {shlex.quote(remote_task_root)}")
    _scp_to(args.host, workload.model, remote_model)
    _scp_to(args.host, workload.input_data, remote_input)
    model_hash = _sha256(workload.model)
    input_hash = _sha256(workload.input_data)

    target, task = _ensure_target_task(session_factory, workload, args, r1)
    _create_run(session_factory, run_id, target, task, workload, args, model_hash, input_hash)

    telemetry = TelemetryOrchestrator(session_factory)
    telemetry_state = OrchestratorState()
    metadata: dict[str, Any] = {}
    try:
        await telemetry.start_run(run_id, _telemetry_sources(args))
        remote = await _run_remote(
            args, workload, run_id, remote_model, remote_input, remote_results, telemetry
        )
        metadata = remote["metadata"]
        telemetry_state = remote["telemetry_state"]
    except Exception as exc:
        if telemetry.state is not None:
            with contextlib.suppress(Exception):
                telemetry_state = await telemetry.stop_run()
        _mark_run_failed(session_factory, run_id, str(exc))
        raise

    results = _parse_results(_remote_capture(args.host, f"cat {shlex.quote(remote_results)}"))
    _write_results(session_factory, run_id, results)
    metrics = _metrics(session_factory, run_id, results, workload)
    _finish_run(session_factory, run_id, results, metrics, metadata, telemetry_state)
    return {
        "run_id": run_id,
        "task": workload.task_id,
        "metrics": metrics,
        "metadata": metadata,
        "lineage": {
            "metric": workload.lineage_metric,
            "value": workload.lineage_value,
            "tolerance": workload.parity_tolerance,
            "eval_note": workload.eval_note,
        },
    }


async def _run_remote(
    args: argparse.Namespace,
    workload: Workload,
    run_id: str,
    remote_model: str,
    remote_input: str,
    remote_results: str,
    telemetry: TelemetryOrchestrator,
) -> dict[str, Any]:
    command = " ".join(
        [
            "<remote-home>",
            shlex.quote(f"{args.remote_root}/scripts/curve_pi5_tflite_device.py"),
            "--model",
            shlex.quote(remote_model),
            "--input-data",
            shlex.quote(remote_input),
            "--task-id",
            shlex.quote(workload.task_id),
            "--task-family",
            shlex.quote(workload.family),
            "--run-id",
            shlex.quote(run_id),
            "--duration-s",
            str(args.duration_s),
            "--threads",
            str(args.threads),
            "--results-jsonl",
            shlex.quote(remote_results),
        ],
    )
    process = await asyncio.create_subprocess_exec(
        "ssh",
        *SSH_OPTS,
        args.host,
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    metadata: dict[str, Any] = {}
    telemetry_state = OrchestratorState()
    assert process.stdout is not None
    while line_bytes := await process.stdout.readline():
        payload = json.loads(line_bytes.decode("utf-8"))
        if payload.get("type") == "metadata":
            metadata = dict(payload["metadata"])
        elif payload.get("type") == "measurement_complete":
            telemetry_state = await telemetry.stop_run()
    stderr = (
        (await process.stderr.read()).decode("utf-8", errors="replace") if process.stderr else ""
    )
    returncode = await process.wait()
    if not telemetry_state.samples_written:
        telemetry_state = await telemetry.stop_run()
    if returncode != 0:
        raise RuntimeError(
            f"remote Pi5 CPU run failed for {workload.task_id} with exit {returncode}:\n{stderr}"
        )
    return {"metadata": metadata, "telemetry_state": telemetry_state, "stderr": stderr}


def _workloads() -> list[Workload]:
    base = Path("<local-path>")
    return [
        Workload(
            task_id="ic",
            family="classification",
            version="x-corpus-ic-float",
            model=base / "ic" / "ic_float.tflite",
            input_data=base / "ic" / "eval_subset.npz",
            lineage_metric="top1",
            lineage_value=0.8577,
            parity_tolerance=0.05,
            eval_note="100-sample CIFAR-10 deterministic eval subset from P4 compile inputs.",
        ),
        Workload(
            task_id="kws",
            family="keyword_spotting",
            version="x-corpus-kws-float",
            model=base / "kws" / "kws_float.tflite",
            input_data=Path("<local-path>"),
            lineage_metric="top1",
            lineage_value=0.8818,
            parity_tolerance=0.03,
            eval_note="Full MLPerf Tiny reference-preprocessed Speech Commands test set, num_test_samples=-1.",
        ),
        Workload(
            task_id="ad",
            family="anomaly_detection",
            version="x-corpus-ad-float",
            model=base / "ad" / "ad_float.tflite",
            input_data=base / "ad" / "eval_clip_frames.npz",
            lineage_metric="clip_auroc",
            lineage_value=0.8391,
            parity_tolerance=0.03,
            eval_note="Deterministic balanced clip-level frame set from P4 compile inputs.",
        ),
    ]


def _capture_r1(host: str) -> dict[str, str]:
    return {
        "host": host,
        "identity": _remote_capture(
            host, "hostname; hostname -I; uname -a; cat /etc/os-release | head -8"
        ),
        "hailo_device": _remote_capture(
            host,
            "ls -la /dev/hailo* 2>/dev/null || echo NO_HAILO_DEV; command -v hailortcli >/dev/null && (hailortcli scan || true) || true",
        ),
        "python": _remote_capture(
            host,
            "~/venvs/edge/bin/python --version; ~/venvs/edge/bin/python - <<'PY'\nimport importlib.metadata\nprint('ai-edge-litert', importlib.metadata.version('ai-edge-litert'))\nPY",
        ),
    }


def _deploy_common(host: str, remote_root: str) -> None:
    _remote_capture(host, f"mkdir -p {shlex.quote(remote_root + '/scripts')}")
    _scp_to(
        host,
        ROOT / "scripts" / "curve_pi5_tflite_device.py",
        f"{remote_root}/scripts/curve_pi5_tflite_device.py",
    )


def _telemetry_sources(args: argparse.Namespace) -> list[TelemetrySource]:
    sources: list[TelemetrySource] = [
        Ina219Source(Ina219Config(address=0x40)),
        Bme280Source(Bme280Config(address=0x77)),
    ]
    if not args.no_fnb58:
        sources.append(FnirsiSource(FnirsiSourceConfig(address=args.fnb58_address)))
    return sources


def _ensure_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/signal_bench/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _ensure_target_task(
    session_factory: sessionmaker[Session],
    workload: Workload,
    args: argparse.Namespace,
    r1: dict[str, str],
) -> tuple[Target, Task]:
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == "pi5-cpu", Target.kind == "sbc")
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name="pi5-cpu",
                kind="sbc",
                cpu="Raspberry Pi 5",
                accelerator=None,
                os_name="Raspberry Pi OS",
                extra={"host": args.host, "power_boundary": "whole-board (INA219/FNB58)", "r1": r1},
            )
            session.add(target)
        task = session.scalar(
            select(Task).where(Task.name == workload.task_id, Task.version == workload.version)
        )
        if task is None:
            task = Task(
                task_id=new_id(),
                name=workload.task_id,
                version=workload.version,
                family=workload.family,
                yaml_path=None,
                yaml_hash=None,
            )
            session.add(task)
        session.commit()
        session.refresh(target)
        session.refresh(task)
        return target, task


def _create_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    target: Target,
    task: Task,
    workload: Workload,
    args: argparse.Namespace,
    model_hash: str,
    input_hash: str,
) -> None:
    with session_factory() as session:
        session.add(
            Run(
                run_id=run_id,
                target_id=target.target_id,
                task_id=task.task_id,
                started_at=dt.datetime.now(dt.UTC),
                status="running",
                corpus_tag="X",
                warmup_count=8,
                measurement_count=0,
                signal_bench_version=__version__,
                runtime_name="ai-edge-litert",
                runtime_version="unknown",
                model_name=workload.model.name,
                model_hash=model_hash,
                quantization="float32",
                notes="Curve Fan-Out Brief A Pi5 CPU-only float X-corpus run.",
                extra={
                    "protocol": "curve-fanout-briefA",
                    "adapter": "Pi5CpuLiteRtAdapter",
                    "model_path": str(workload.model),
                    "input_data": str(workload.input_data),
                    "input_sha256": input_hash,
                    "power_boundary": "whole-board (INA219/FNB58)",
                    "duration_s": args.duration_s,
                    "threads": args.threads,
                    "lineage": {
                        "metric": workload.lineage_metric,
                        "value": workload.lineage_value,
                        "tolerance": workload.parity_tolerance,
                        "eval_note": workload.eval_note,
                    },
                },
                telemetry_partial=False,
            ),
        )
        session.commit()


def _write_results(
    session_factory: sessionmaker[Session], run_id: str, results: list[InferenceResult]
) -> None:
    with session_factory() as session:
        for result in results:
            duration_ms = result.duration_us / 1000.0 if result.duration_us else None
            session.add(
                Result(
                    result_id=new_id(),
                    run_id=run_id,
                    sequence=result.sequence,
                    started_at=result.timestamp,
                    duration_ms=duration_ms,
                    throughput_unit="inferences/s",
                    throughput_value=(
                        1000 / duration_ms if duration_ms and duration_ms > 0 else None
                    ),
                    accuracy_value=None,
                    extra={
                        "data_index": result.data_index,
                        "output": result.output,
                        "error": result.error,
                    },
                ),
            )
        session.commit()


def _finish_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[InferenceResult],
    metrics: dict[str, Any],
    metadata: dict[str, Any],
    telemetry_state: OrchestratorState,
) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        extra = dict(run.extra or {}) if run is not None else {}
        extra["run_metadata"] = metadata
        extra["metrics"] = metrics
        extra["telemetry_state"] = {
            "samples_written": telemetry_state.samples_written,
            "rows_written": telemetry_state.rows_written,
            "samples_per_source": telemetry_state.samples_per_source,
            "rows_per_source": telemetry_state.rows_per_source,
            "partial_reasons": telemetry_state.partial_reasons,
        }
        session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(
                finished_at=dt.datetime.now(dt.UTC),
                status="completed",
                measurement_count=len([item for item in results if item.error is None]),
                runtime_version=str(metadata.get("runtime_version", "unknown")),
                extra=extra,
            ),
        )
        session.commit()


def _mark_run_failed(session_factory: sessionmaker[Session], run_id: str, error: str) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        extra = dict(run.extra or {})
        extra["error"] = error
        session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(finished_at=dt.datetime.now(dt.UTC), status="failed", extra=extra)
        )
        session.commit()


def _metrics(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[InferenceResult],
    workload: Workload,
) -> dict[str, Any]:
    successful = [item for item in results if item.error is None and item.duration_us > 0]
    latencies = [item.duration_us / 1000.0 for item in successful]
    accuracy = _accuracy_proxy(successful, workload)
    return {
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": statistics.median(latencies) if latencies else None,
            "p99": _percentile(latencies, 99) if latencies else None,
        },
        "inference_count": len(successful),
        "output_sanity": {
            "valid_outputs": len(successful),
            "unique_argmax_count": _unique_argmax_count(successful),
            "garbage": not successful,
        },
        "accuracy_proxy": accuracy,
        "telemetry": _telemetry_counts(session_factory, run_id),
        "energy": _energy_metrics(session_factory, run_id, len(successful)),
    }


def _accuracy_proxy(results: list[InferenceResult], workload: Workload) -> dict[str, Any]:
    if workload.family in {"classification", "keyword_spotting"}:
        predictions = [
            int(item.output.get("argmax")) for item in results if "argmax" in item.output
        ]
        labels = [
            int(item.output.get("label"))
            for item in results
            if item.output.get("label") is not None
        ]
        value = (
            float(sum(p == y for p, y in zip(predictions, labels, strict=False)) / len(predictions))
            if predictions
            else 0.0
        )
        delta = value - workload.lineage_value
        return {
            "metric": "top1",
            "value": value,
            "lineage": workload.lineage_value,
            "delta": delta,
            "pass": abs(delta) <= workload.parity_tolerance,
        }
    grouped: dict[str, list[float]] = {}
    truth: dict[str, int] = {}
    for item in results:
        source = item.output.get("source")
        if source is None:
            continue
        grouped.setdefault(str(source), []).append(float(item.output["score"]))
        truth.setdefault(str(source), int(item.output["label"]))
    ordered_sources = sorted(grouped)
    scores = [statistics.fmean(grouped[source]) for source in ordered_sources]
    labels = [truth[source] for source in ordered_sources]
    value = _binary_auc(labels, scores)
    delta = (value - workload.lineage_value) if value is not None else None
    return {
        "metric": "clip_auroc",
        "value": value,
        "lineage": workload.lineage_value,
        "delta": delta,
        "groups": len(scores),
        "pass": value is not None and abs(delta or 0.0) <= workload.parity_tolerance,
    }


def _telemetry_counts(session_factory: sessionmaker[Session], run_id: str) -> dict[str, Any]:
    with session_factory() as session:
        rows = session.execute(
            select(TelemetrySample.source, TelemetrySample.metric, func.count())
            .where(TelemetrySample.run_id == run_id)
            .group_by(TelemetrySample.source, TelemetrySample.metric),
        ).all()
        run = session.get(Run, run_id)
    by_source: dict[str, dict[str, int]] = {}
    for source, metric, count in rows:
        by_source.setdefault(str(source), {})[str(metric)] = int(count)
    return {
        "grouped_instants": {
            source: max(metrics.values()) for source, metrics in by_source.items()
        },
        "rows": by_source,
        "partial": bool(run.telemetry_partial) if run is not None else True,
        "partial_sources": list(run.telemetry_partial_sources or []) if run is not None else [],
    }


def _energy_metrics(
    session_factory: sessionmaker[Session], run_id: str, inference_count: int
) -> dict[str, Any]:
    sources = {
        "ina219": _wh_per_1000_from_source(session_factory, run_id, "ina219", inference_count),
        "fnb58": _wh_per_1000_from_source(session_factory, run_id, "fnb58", inference_count),
    }
    headline = (
        sources["ina219"]
        if sources["ina219"]["wh_per_1000_inferences"] is not None
        else sources["fnb58"]
    )
    return {"headline_source": headline["source"], "headline": headline, "by_source": sources}


def _wh_per_1000_from_source(
    session_factory: sessionmaker[Session],
    run_id: str,
    source: str,
    inference_count: int,
) -> dict[str, Any]:
    if inference_count <= 0:
        return {
            "source": source,
            "wh_per_1000_inferences": None,
            "avg_power_w": None,
            "duration_s": None,
        }
    with session_factory() as session:
        samples = session.scalars(
            select(TelemetrySample)
            .where(
                TelemetrySample.run_id == run_id,
                TelemetrySample.source == source,
                TelemetrySample.metric == "power",
            )
            .order_by(TelemetrySample.timestamp),
        ).all()
    if len(samples) < 2:
        return {
            "source": source,
            "wh_per_1000_inferences": None,
            "avg_power_w": None,
            "duration_s": None,
        }
    joules = 0.0
    total_s = 0.0
    for previous, current in zip(samples, samples[1:], strict=False):
        dt_s = (current.timestamp - previous.timestamp).total_seconds()
        if dt_s > 0:
            joules += ((previous.value + current.value) / 2.0) * dt_s
            total_s += dt_s
    return {
        "source": source,
        "wh_per_1000_inferences": (
            joules / 3600.0 / inference_count * 1000.0 if total_s > 0 else None
        ),
        "avg_power_w": joules / total_s if total_s > 0 else None,
        "duration_s": total_s,
    }


def _parse_results(text: str) -> list[InferenceResult]:
    results = []
    for line in text.splitlines():
        payload = json.loads(line)
        results.append(
            InferenceResult(
                sequence=int(payload["iter_id"]),
                data_index=int(payload["data_index"]),
                timestamp=dt.datetime.fromisoformat(payload["timestamp"]),
                duration_us=int(payload["duration_us"]),
                output=dict(payload["output"]),
                error=payload["error"],
            ),
        )
    return results


def _write_report(report_path: Path, r1: dict[str, str], summaries: list[dict[str, Any]]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Curve Fan-Out Brief A",
        "",
        "## Summary",
        f"1. Pi5 CPU-only card-out gate: PASS (`/dev/hailo0` absent); host `{r1['host']}`.",
        "2. Pi5 CPU runtime: ai-edge-litert CPU/XNNPACK, batch 1, whole-board power via INA219 headline with FNB58 cross-check.",
        "3. Modal A10G: R1 found no existing X-corpus IC/KWS/AD rows and no reusable NVML-backed measurement function in this repo; not measured in this Pi-focused run.",
        "4. M1 Max: R1 found no macOS powermetrics/on-die power source; M1 tier is stopped rather than emitting a partial telemetry row.",
        "5. Power boundary: Pi5 = whole-board input power; Modal = GPU package once built; M1 = device package once powermetrics source exists.",
        "6. Proprietary binaries: none copied into the repo; float models/eval data stayed under `<local-path>`.",
        "",
        "## Pi5 CPU Results",
        "",
        "| task | status | Wh/1000 (INA219) | avg W (INA219) | latency mean ms | p50 ms | p99 ms | accuracy proxy | lineage | partial | inferences |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |",
    ]
    for summary in summaries:
        metrics = summary["metrics"]
        acc = metrics["accuracy_proxy"]
        energy = metrics["energy"]["by_source"]["ina219"]
        latency = metrics["latency_ms"]
        status = "pass" if acc["pass"] and not metrics["telemetry"]["partial"] else "fail"
        lines.append(
            "| {task} | {status} | {wh} | {avg} | {mean} | {p50} | {p99} | {acc_metric}={acc_value} | {lineage_metric}={lineage_value} | {partial} | {count} |".format(
                task=summary["task"],
                status=status,
                wh=_fmt(energy["wh_per_1000_inferences"]),
                avg=_fmt(energy["avg_power_w"]),
                mean=_fmt(latency["mean"]),
                p50=_fmt(latency["p50"]),
                p99=_fmt(latency["p99"]),
                acc_metric=acc["metric"],
                acc_value=_fmt(acc["value"], 4),
                lineage_metric=summary["lineage"]["metric"],
                lineage_value=_fmt(summary["lineage"]["value"], 4),
                partial=metrics["telemetry"]["partial"],
                count=metrics["inference_count"],
            ),
        )
    lines.extend(
        [
            "",
            "## Per-Run JSON",
            "",
            "```json",
            json.dumps(summaries, indent=2, sort_keys=True),
            "```",
            "",
            "## R1 / Card-Out Sanity",
            "",
            "```text",
            "IDENTITY",
            r1["identity"].strip(),
            "",
            "HAILO DEVICE",
            r1["hailo_device"].strip(),
            "",
            "PYTHON",
            r1["python"].strip(),
            "```",
            "",
            "## Tier Gaps",
            "",
            "- `m1-max`: build a macOS power source around `powermetrics`/on-die counters before running; otherwise the curve row would be `partial=true`.",
            "- `modal-a10g`: build or identify a CUDA/GPU X-corpus inference function with NVML power capture; existing Modal code in this repo is LLM/Ollama or DFC compile, not this measurement lane.",
        ],
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: float | None, digits: int = 6) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:.{digits}g}"


def _unique_argmax_count(results: list[InferenceResult]) -> int | None:
    values = [item.output.get("argmax") for item in results if "argmax" in item.output]
    return len(set(values)) if values else None


def _binary_auc(labels: list[int], scores: list[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores, strict=True) if label == 1]
    negatives = [score for label, score in zip(labels, scores, strict=True) if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for pos in positives:
        for neg in negatives:
            wins += 1.0 if pos > neg else 0.5 if pos == neg else 0.0
    return wins / (len(positives) * len(negatives))


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configure_telemetry_env() -> None:
    os.environ.setdefault("BLINKA_MCP2221", "1")
    os.environ.setdefault("SIGNAL_BENCH_REAL_I2C", "1")
    os.environ.setdefault("FNB58_TRANSPORT", "ble")


def _remote_capture(host: str, command_text: str, *, check: bool = True) -> str:
    process = subprocess.run(
        ["ssh", *SSH_OPTS, host, command_text],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (process.stdout or "") + (process.stderr or "")
    if check and process.returncode != 0:
        raise RuntimeError(output.strip() or f"ssh command failed with exit {process.returncode}")
    return output


def _scp_to(host: str, local: Path, remote: str) -> None:
    destination = f"{host}:{remote}"
    process = subprocess.run(
        ["scp", *SSH_OPTS, str(local), destination],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError((process.stdout or "") + (process.stderr or ""))


if __name__ == "__main__":
    raise SystemExit(main())
