# SPDX-License-Identifier: Apache-2.0
"""Run Curve Fan-Out Brief A2 M1 Max CPU-only X-corpus measurements."""

# ruff: noqa: RUF007

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ai_edge_litert.interpreter import Interpreter
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Result, Run, Target, Task, TelemetrySample
from signal_bench.telemetry.orchestrator import OrchestratorState, TelemetryOrchestrator
from signal_bench.telemetry.sources.powermetrics import PowermetricsConfig, PowermetricsSource

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curve_fanout_briefA.db"
REPORT_JSON = ROOT / "reports" / "scratch" / "curve_m1_cpu_results.json"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--duration-s", type=float, default=35.0)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-result-rows", type=int, default=200_000)
    parser.add_argument("--only", choices=["ic", "kws", "ad"], action="append")
    parser.add_argument("--results-json", type=Path, default=REPORT_JSON)
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


async def _main_async(args: argparse.Namespace) -> int:
    _ensure_database(args.db)
    engine = create_engine(f"sqlite:///{args.db}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    workloads = [item for item in _workloads() if not args.only or item.task_id in set(args.only)]
    summaries = []
    for workload in workloads:
        summary = await _run_workload(args, session_factory, workload)
        summaries.append(summary)
        print(json.dumps({"task": workload.task_id, "summary": summary}, sort_keys=True))

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(
        json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


async def _run_workload(
    args: argparse.Namespace,
    session_factory: sessionmaker[Session],
    workload: Workload,
) -> dict[str, Any]:
    run_id = new_id()
    model_hash = _sha256(workload.model)
    input_hash = _sha256(workload.input_data)
    target, task = _ensure_target_task(session_factory, workload)
    _create_run(session_factory, run_id, target, task, workload, args, model_hash, input_hash)

    telemetry = TelemetryOrchestrator(session_factory)
    telemetry_state = OrchestratorState()
    try:
        await telemetry.start_run(run_id, [PowermetricsSource(PowermetricsConfig())])
        local = await asyncio.to_thread(
            _run_litert,
            workload,
            args.duration_s,
            args.warmup,
            args.threads,
            args.max_result_rows,
        )
        telemetry_state = await telemetry.stop_run()
    except Exception as exc:
        if telemetry.state is not None:
            with contextlib.suppress(Exception):
                telemetry_state = await telemetry.stop_run()
        _mark_run_failed(session_factory, run_id, str(exc))
        raise

    _write_results(session_factory, run_id, local["result_rows"])
    metrics = _metrics(session_factory, run_id, local, workload)
    _finish_run(session_factory, run_id, local, metrics, telemetry_state)
    accuracy = metrics["accuracy_proxy"]
    return {
        "run_id": run_id,
        "task": workload.task_id,
        "status": "pass" if accuracy["pass"] and not metrics["telemetry"]["partial"] else "fail",
        "latency_ms": metrics["latency_ms"],
        "accuracy_proxy": accuracy,
        "energy": metrics["energy"]["headline"],
        "telemetry": metrics["telemetry"],
        "metadata": local["metadata"],
    }


def _run_litert(
    workload: Workload,
    duration_s: float,
    warmup: int,
    threads: int,
    max_result_rows: int,
) -> dict[str, Any]:
    archive = np.load(workload.input_data, allow_pickle=False)
    inputs = archive["inputs"].astype(np.float32, copy=False)
    labels = archive["labels"].astype(np.int64, copy=False) if "labels" in archive else None
    sources = archive["sources"].astype(str, copy=False) if "sources" in archive else None

    interpreter = Interpreter(model_path=str(workload.model), num_threads=threads)
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    interpreter.resize_tensor_input(input_detail["index"], [1, *inputs.shape[1:]], strict=False)
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]

    for index in range(min(warmup, len(inputs))):
        interpreter.set_tensor(input_detail["index"], inputs[index : index + 1])
        interpreter.invoke()

    accuracy = _evaluate_accuracy(
        interpreter, input_detail, output_detail, inputs, labels, sources, workload.family
    )
    result_rows, latency_summary, measurement_count = _measure(
        interpreter,
        input_detail,
        output_detail,
        inputs,
        labels,
        sources,
        workload.family,
        duration_s,
        max_result_rows,
    )
    return {
        "accuracy_proxy": accuracy,
        "latency_ms": latency_summary,
        "measurement_count": measurement_count,
        "result_rows": result_rows,
        "metadata": {
            "runtime_name": "ai-edge-litert",
            "runtime_version": importlib.metadata.version("ai-edge-litert"),
            "execution_provider": "CPU/XNNPACK",
            "python": platform.python_version(),
            "kernel": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "threads": threads,
            "batch_size": 1,
            "input_shape": list(inputs.shape[1:]),
            "input_count": int(inputs.shape[0]),
            "input_tensor": _tensor_detail(input_detail),
            "output_tensor": _tensor_detail(output_detail),
            "power_boundary": "device package (powermetrics)",
        },
    }


def _evaluate_accuracy(
    interpreter: Interpreter,
    input_detail: dict[str, Any],
    output_detail: dict[str, Any],
    inputs: np.ndarray,
    labels: np.ndarray | None,
    sources: np.ndarray | None,
    family: str,
) -> dict[str, Any]:
    if family in {"classification", "keyword_spotting"}:
        correct = 0
        assert labels is not None
        for index in range(len(inputs)):
            output = _invoke(interpreter, input_detail, output_detail, inputs[index : index + 1])
            correct += int(int(np.argmax(output.reshape(-1))) == int(labels[index]))
        return {"metric": "top1", "value": correct / len(inputs), "eval_count": len(inputs)}

    assert labels is not None
    assert sources is not None
    grouped: dict[str, list[float]] = {}
    truth: dict[str, int] = {}
    for index in range(len(inputs)):
        sample = inputs[index : index + 1]
        output = _invoke(interpreter, input_detail, output_detail, sample)
        score = float(
            np.mean(
                (output.reshape(-1).astype(np.float32) - sample.reshape(-1).astype(np.float32)) ** 2
            )
        )
        source = str(sources[index])
        grouped.setdefault(source, []).append(score)
        truth.setdefault(source, int(labels[index]))
    ordered = sorted(grouped)
    scores = [statistics.fmean(grouped[source]) for source in ordered]
    ordered_labels = [truth[source] for source in ordered]
    return {
        "metric": "clip_auroc",
        "value": _binary_auc(ordered_labels, scores),
        "eval_count": len(inputs),
        "groups": len(ordered),
    }


def _measure(
    interpreter: Interpreter,
    input_detail: dict[str, Any],
    output_detail: dict[str, Any],
    inputs: np.ndarray,
    labels: np.ndarray | None,
    sources: np.ndarray | None,
    family: str,
    duration_s: float,
    max_result_rows: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    durations: list[float] = []
    result_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    sequence = 0
    while time.perf_counter() - started < duration_s:
        data_index = sequence % len(inputs)
        sample = inputs[data_index : data_index + 1]
        timestamp = dt.datetime.now(dt.UTC)
        t0 = time.perf_counter_ns()
        output = _invoke(interpreter, input_detail, output_detail, sample)
        duration_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        durations.append(duration_ms)
        if len(result_rows) < max_result_rows:
            result_rows.append(
                {
                    "sequence": sequence,
                    "data_index": int(data_index),
                    "timestamp": timestamp.isoformat(),
                    "duration_ms": duration_ms,
                    "output": _output_summary(
                        output,
                        sample,
                        family,
                        int(labels[data_index]) if labels is not None else None,
                        str(sources[data_index]) if sources is not None else None,
                    ),
                },
            )
        sequence += 1
    return result_rows, _latency_summary(durations), len(durations)


def _invoke(
    interpreter: Interpreter,
    input_detail: dict[str, Any],
    output_detail: dict[str, Any],
    sample: np.ndarray,
) -> np.ndarray:
    interpreter.set_tensor(input_detail["index"], sample)
    interpreter.invoke()
    return interpreter.get_tensor(output_detail["index"])


def _output_summary(
    raw_output: np.ndarray,
    sample: np.ndarray,
    family: str,
    label: int | None,
    source: str | None,
) -> dict[str, Any]:
    values = raw_output.reshape(-1).astype(np.float32)
    if family in {"classification", "keyword_spotting"}:
        argmax = int(np.argmax(values))
        return {"argmax": argmax, "confidence": float(values[argmax]), "label": label}
    sample_values = sample.reshape(-1).astype(np.float32)
    return {
        "score": float(np.mean((values - sample_values) ** 2)),
        "label": label,
        "source": source,
    }


def _workloads() -> list[Workload]:
    base = Path("<local-path>")
    return [
        Workload(
            "ic",
            "classification",
            "x-corpus-ic-float-m1",
            base / "ic" / "ic_float.tflite",
            base / "ic" / "eval_subset.npz",
            "top1",
            0.8577,
            0.05,
            "100-sample CIFAR-10 deterministic eval subset from P4 compile inputs.",
        ),
        Workload(
            "kws",
            "keyword_spotting",
            "x-corpus-kws-float-m1",
            base / "kws" / "kws_float.tflite",
            Path("<local-path>"),
            "top1",
            0.8818,
            0.03,
            "Full MLPerf Tiny reference-preprocessed Speech Commands test set, num_test_samples=-1.",
        ),
        Workload(
            "ad",
            "anomaly_detection",
            "x-corpus-ad-float-m1",
            base / "ad" / "ad_float.tflite",
            base / "ad" / "eval_clip_frames.npz",
            "clip_auroc",
            0.8391,
            0.03,
            "Deterministic balanced clip-level frame set from P4 compile inputs.",
        ),
    ]


def _ensure_target_task(
    session_factory: sessionmaker[Session],
    workload: Workload,
) -> tuple[Target, Task]:
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == "m1-max", Target.kind == "laptop")
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name="m1-max",
                kind="laptop",
                cpu="Apple M1 Max",
                accelerator=None,
                os_name="macOS",
                os_version=platform.platform(),
                extra={"power_boundary": "device package (powermetrics)"},
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
                warmup_count=args.warmup,
                measurement_count=0,
                signal_bench_version=__version__,
                runtime_name="ai-edge-litert",
                runtime_version=importlib.metadata.version("ai-edge-litert"),
                model_name=workload.model.name,
                model_hash=model_hash,
                quantization="float32",
                notes="Curve Fan-Out Brief A2 M1 Max CPU-only float X-corpus run.",
                extra={
                    "protocol": "curve-fanout-briefA2",
                    "adapter": "M1CpuLiteRtAdapter",
                    "model_path": str(workload.model),
                    "input_data": str(workload.input_data),
                    "input_sha256": input_hash,
                    "power_boundary": "device package (powermetrics)",
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
    session_factory: sessionmaker[Session], run_id: str, rows: list[dict[str, Any]]
) -> None:
    with session_factory() as session:
        for row in rows:
            duration_ms = float(row["duration_ms"])
            session.add(
                Result(
                    result_id=new_id(),
                    run_id=run_id,
                    sequence=int(row["sequence"]),
                    started_at=dt.datetime.fromisoformat(row["timestamp"]),
                    duration_ms=duration_ms,
                    throughput_unit="inferences/s",
                    throughput_value=1000 / duration_ms if duration_ms > 0 else None,
                    accuracy_value=None,
                    extra={
                        "data_index": int(row["data_index"]),
                        "output": row["output"],
                        "sampled_result_rows": True,
                    },
                ),
            )
        session.commit()


def _finish_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    local: dict[str, Any],
    metrics: dict[str, Any],
    telemetry_state: OrchestratorState,
) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        extra = dict(run.extra or {}) if run is not None else {}
        extra["run_metadata"] = local["metadata"]
        extra["metrics"] = metrics
        extra["result_rows_sampled"] = len(local["result_rows"])
        extra["telemetry_state"] = {
            "samples_written": telemetry_state.samples_written,
            "rows_written": telemetry_state.rows_written,
            "samples_per_source": telemetry_state.samples_per_source,
            "rows_per_source": telemetry_state.rows_per_source,
            "partial_reasons": telemetry_state.partial_reasons,
        }
        status = (
            "completed"
            if metrics["accuracy_proxy"]["pass"] and not metrics["telemetry"]["partial"]
            else "failed"
        )
        session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(
                finished_at=dt.datetime.now(dt.UTC),
                status=status,
                measurement_count=int(local["measurement_count"]),
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
    local: dict[str, Any],
    workload: Workload,
) -> dict[str, Any]:
    accuracy = dict(local["accuracy_proxy"])
    accuracy["lineage"] = workload.lineage_value
    accuracy["delta"] = (
        accuracy["value"] - workload.lineage_value if accuracy.get("value") is not None else None
    )
    accuracy["pass"] = (
        accuracy["delta"] is not None and abs(accuracy["delta"]) <= workload.parity_tolerance
    )
    return {
        "latency_ms": local["latency_ms"],
        "inference_count": int(local["measurement_count"]),
        "accuracy_proxy": accuracy,
        "telemetry": _telemetry_counts(session_factory, run_id),
        "energy": _energy_metrics(session_factory, run_id, int(local["measurement_count"])),
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
    headline = _wh_per_1000_from_source(session_factory, run_id, "powermetrics", inference_count)
    return {
        "headline_source": "powermetrics",
        "headline": headline,
        "by_source": {"powermetrics": headline},
    }


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


def _ensure_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/signal_bench/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _latency_summary(values: list[float]) -> dict[str, Any]:
    return {
        "mean": statistics.fmean(values) if values else None,
        "p50": statistics.median(values) if values else None,
        "p99": _percentile(values, 99) if values else None,
        "count": len(values),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


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


def _tensor_detail(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(detail.get("name")),
        "shape": np.asarray(detail.get("shape")).astype(int).tolist(),
        "shape_signature": np.asarray(detail.get("shape_signature")).astype(int).tolist(),
        "dtype": getattr(detail.get("dtype"), "__name__", str(detail.get("dtype"))),
        "quantization": list(detail.get("quantization", (0.0, 0))),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
