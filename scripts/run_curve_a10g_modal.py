# SPDX-License-Identifier: Apache-2.0
"""Run Curve Fan-Out Brief A2 Modal A10G X-corpus measurements."""

# ruff: noqa: RUF007

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import modal

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curve_fanout_briefA.db"
REPORT_JSON = ROOT / "reports" / "scratch" / "curve_a10g_modal_results.json"
APP_NAME = "signal-bench-curve-a10g"


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


image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04", add_python="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(
        "numpy==1.26.4",
        "onnx==1.17.0",
        "onnxruntime-gpu==1.20.1",
        "tensorflow-cpu==2.16.1",
        "tf2onnx==1.16.1",
        "nvidia-ml-py==12.560.30",
    )
)
app = modal.App(APP_NAME)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--duration-s", type=float, default=35.0)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--max-result-rows", type=int, default=200_000)
    parser.add_argument("--only", choices=["ic", "kws", "ad"], action="append")
    parser.add_argument("--results-json", type=Path, default=REPORT_JSON)
    args = parser.parse_args()
    return _run_from_values(
        args.db, args.duration_s, args.warmup, args.max_result_rows, args.only, args.results_json
    )


@app.local_entrypoint()
def modal_main(
    db: str = str(DB_PATH),
    duration_s: float = 35.0,
    warmup: int = 8,
    max_result_rows: int = 200_000,
    only: str = "",
    results_json: str = str(REPORT_JSON),
) -> None:
    """Modal CLI entrypoint."""
    selected = [item.strip() for item in only.split(",") if item.strip()] or None
    raise SystemExit(
        _run_from_values(
            Path(db),
            duration_s,
            warmup,
            max_result_rows,
            selected,
            Path(results_json),
        ),
    )


def _run_from_values(
    db: Path,
    duration_s: float,
    warmup: int,
    max_result_rows: int,
    only: list[str] | None,
    results_json: Path,
) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _ensure_database(db)
    engine = create_engine(f"sqlite:///{db}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    workloads = [item for item in _workloads() if not only or item.task_id in set(only)]

    summaries = []
    for workload in workloads:
        payload = _payload_for(workload)
        remote = run_workload.remote(
            workload.task_id,
            workload.family,
            payload["model"],
            payload["input_data"],
            duration_s,
            warmup,
            max_result_rows,
        )
        summary = _record_run(session_factory, workload, remote, payload)
        summaries.append(summary)
        print(json.dumps({"task": workload.task_id, "summary": summary}, sort_keys=True))

    results_json.parent.mkdir(parents=True, exist_ok=True)
    results_json.write_text(
        json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


@app.function(image=image, gpu="A10G", timeout=3600)
def run_workload(
    task_id: str,
    family: str,
    model_bytes: bytes,
    input_bytes: bytes,
    duration_s: float,
    warmup: int,
    max_result_rows: int,
) -> dict[str, Any]:
    """Convert one TFLite model to ONNX, run it on CUDA, and sample NVML power."""
    import numpy as np
    import onnxruntime as ort
    import pynvml

    work_dir = Path(tempfile.mkdtemp(prefix=f"signal-bench-{task_id}-"))
    model_path = work_dir / f"{task_id}.tflite"
    input_path = work_dir / f"{task_id}.npz"
    onnx_path = work_dir / f"{task_id}.onnx"
    model_path.write_bytes(model_bytes)
    input_path.write_bytes(input_bytes)

    converted = subprocess.run(
        [
            sys.executable,
            "-m",
            "tf2onnx.convert",
            "--tflite",
            str(model_path),
            "--output",
            str(onnx_path),
            "--opset",
            "17",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if converted.returncode != 0:
        raise RuntimeError(
            "TFLite-to-ONNX conversion failed:\n"
            f"STDOUT:\n{converted.stdout}\nSTDERR:\n{converted.stderr}",
        )

    session = ort.InferenceSession(
        str(onnx_path),
        providers=["CUDAExecutionProvider"],
    )
    active_providers = session.get_providers()
    if "CUDAExecutionProvider" not in active_providers:
        raise RuntimeError(f"CUDAExecutionProvider not active: {active_providers}")
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    archive = np.load(input_path, allow_pickle=False)
    inputs = archive["inputs"].astype(np.float32, copy=False)
    labels = archive["labels"].astype(np.int64, copy=False) if "labels" in archive else None
    sources = archive["sources"].astype(str, copy=False) if "sources" in archive else None

    for index in range(min(warmup, len(inputs))):
        session.run([output_name], {input_name: inputs[index : index + 1]})

    eval_summary = _remote_accuracy(
        session, input_name, output_name, inputs, labels, sources, family
    )
    power_samples, latency_summary, result_rows = _remote_measure(
        session,
        input_name,
        output_name,
        inputs,
        labels,
        sources,
        family,
        duration_s,
        max_result_rows,
        pynvml,
    )
    energy = _remote_energy(power_samples, latency_summary["count"])
    return {
        "task_id": task_id,
        "family": family,
        "runtime_name": "onnxruntime-gpu",
        "runtime_version": ort.__version__,
        "execution_provider": "CUDAExecutionProvider",
        "active_providers": active_providers,
        "gpu": _remote_gpu_info(pynvml),
        "python": sys.version.split()[0],
        "onnx_opset": 17,
        "duration_s": duration_s,
        "input_shape": list(inputs.shape[1:]),
        "input_count": int(inputs.shape[0]),
        "input_name": input_name,
        "output_name": output_name,
        "conversion_stdout_tail": converted.stdout[-2000:],
        "conversion_stderr_tail": converted.stderr[-2000:],
        "accuracy_proxy": eval_summary,
        "latency_ms": latency_summary,
        "energy": energy,
        "telemetry": {
            "source": "nvml",
            "metric": "power",
            "count": len(power_samples),
            "partial": len(power_samples) < max(2, int(duration_s * 8)),
        },
        "power_samples": power_samples,
        "result_rows": result_rows,
        "result_rows_sampled": len(result_rows),
        "measurement_count": int(latency_summary["count"]),
        "power_boundary": "GPU package (NVML)",
    }


def _remote_measure(
    session: Any,
    input_name: str,
    output_name: str,
    inputs: Any,
    labels: Any,
    sources: Any,
    family: str,
    duration_s: float,
    max_result_rows: int,
    pynvml: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    pynvml.nvmlInit()
    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    power_samples: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    durations: list[float] = []
    started_perf = time.perf_counter()
    started_wall = dt.datetime.now(dt.UTC)
    next_power = started_perf
    sequence = 0
    while time.perf_counter() - started_perf < duration_s:
        now = time.perf_counter()
        if now >= next_power:
            power_w = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            power_samples.append(
                {
                    "timestamp": (
                        started_wall + dt.timedelta(seconds=now - started_perf)
                    ).isoformat(),
                    "power_w": float(power_w),
                },
            )
            next_power = now + 0.1
        data_index = sequence % len(inputs)
        sample = inputs[data_index : data_index + 1]
        timestamp = started_wall + dt.timedelta(seconds=time.perf_counter() - started_perf)
        t0 = time.perf_counter_ns()
        raw_output = session.run([output_name], {input_name: sample})[0]
        duration_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        durations.append(duration_ms)
        if len(result_rows) < max_result_rows:
            result_rows.append(
                {
                    "sequence": sequence,
                    "data_index": int(data_index),
                    "timestamp": timestamp.isoformat(),
                    "duration_ms": float(duration_ms),
                    "output": _remote_output_summary(
                        raw_output,
                        sample,
                        family,
                        int(labels[data_index]) if labels is not None else None,
                        str(sources[data_index]) if sources is not None else None,
                    ),
                },
            )
        sequence += 1
    pynvml.nvmlShutdown()
    return power_samples, _latency_summary(durations), result_rows


def _remote_accuracy(
    session: Any,
    input_name: str,
    output_name: str,
    inputs: Any,
    labels: Any,
    sources: Any,
    family: str,
) -> dict[str, Any]:
    import numpy as np

    if family in {"classification", "keyword_spotting"}:
        correct = 0
        for index in range(len(inputs)):
            output = session.run([output_name], {input_name: inputs[index : index + 1]})[0]
            correct += int(int(np.argmax(output.reshape(-1))) == int(labels[index]))
        return {"metric": "top1", "value": correct / len(inputs), "eval_count": len(inputs)}

    grouped: dict[str, list[float]] = {}
    truth: dict[str, int] = {}
    for index in range(len(inputs)):
        sample = inputs[index : index + 1]
        output = session.run([output_name], {input_name: sample})[0]
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


def _remote_output_summary(
    raw_output: Any, sample: Any, family: str, label: int | None, source: str | None
) -> dict[str, Any]:
    import numpy as np

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


def _remote_energy(power_samples: list[dict[str, Any]], inference_count: int) -> dict[str, Any]:
    if len(power_samples) < 2 or inference_count <= 0:
        return {
            "source": "nvml",
            "wh_per_1000_inferences": None,
            "avg_power_w": None,
            "duration_s": None,
        }
    joules = 0.0
    total_s = 0.0
    parsed = [
        (dt.datetime.fromisoformat(item["timestamp"]), float(item["power_w"]))
        for item in power_samples
    ]
    for previous, current in zip(parsed, parsed[1:], strict=False):
        dt_s = (current[0] - previous[0]).total_seconds()
        if dt_s > 0:
            joules += ((previous[1] + current[1]) / 2.0) * dt_s
            total_s += dt_s
    return {
        "source": "nvml",
        "wh_per_1000_inferences": (
            joules / 3600.0 / inference_count * 1000.0 if total_s > 0 else None
        ),
        "avg_power_w": joules / total_s if total_s > 0 else None,
        "duration_s": total_s,
    }


def _remote_gpu_info(pynvml: Any) -> dict[str, Any]:
    pynvml.nvmlInit()
    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    info = {
        "name": (
            pynvml.nvmlDeviceGetName(handle).decode()
            if isinstance(pynvml.nvmlDeviceGetName(handle), bytes)
            else str(pynvml.nvmlDeviceGetName(handle))
        ),
        "memory_total_mb": int(pynvml.nvmlDeviceGetMemoryInfo(handle).total / 1024 / 1024),
        "driver_version": (
            pynvml.nvmlSystemGetDriverVersion().decode()
            if isinstance(pynvml.nvmlSystemGetDriverVersion(), bytes)
            else str(pynvml.nvmlSystemGetDriverVersion())
        ),
    }
    pynvml.nvmlShutdown()
    return info


def _workloads() -> list[Workload]:
    base = Path("<local-path>")
    return [
        Workload(
            "ic",
            "classification",
            "x-corpus-ic-float-a10g",
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
            "x-corpus-kws-float-a10g",
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
            "x-corpus-ad-float-a10g",
            base / "ad" / "ad_float.tflite",
            base / "ad" / "eval_clip_frames.npz",
            "clip_auroc",
            0.8391,
            0.03,
            "Deterministic balanced clip-level frame set from P4 compile inputs.",
        ),
    ]


def _payload_for(workload: Workload) -> dict[str, bytes]:
    return {"model": workload.model.read_bytes(), "input_data": workload.input_data.read_bytes()}


def _record_run(
    session_factory: Any,
    workload: Workload,
    remote: dict[str, Any],
    payload: dict[str, bytes],
) -> dict[str, Any]:
    from sqlalchemy import select

    from signal_bench import __version__
    from signal_bench.ids import new_id
    from signal_bench.schema import Result, Run, Target, Task, TelemetrySample

    run_id = new_id()
    model_hash = hashlib.sha256(payload["model"]).hexdigest()
    input_hash = hashlib.sha256(payload["input_data"]).hexdigest()
    accuracy = dict(remote["accuracy_proxy"])
    accuracy["lineage"] = workload.lineage_value
    accuracy["delta"] = (
        accuracy["value"] - workload.lineage_value if accuracy.get("value") is not None else None
    )
    accuracy["pass"] = (
        accuracy["delta"] is not None and abs(accuracy["delta"]) <= workload.parity_tolerance
    )
    partial = (
        bool(remote["telemetry"]["partial"]) or remote["energy"]["wh_per_1000_inferences"] is None
    )
    partial_sources = ["nvml"] if partial else []

    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == "modal-a10g", Target.kind == "cloud_gpu")
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name="modal-a10g",
                kind="cloud_gpu",
                cpu="Modal worker x86_64",
                accelerator="NVIDIA A10G",
                os_name="Ubuntu 22.04 container",
                extra={"modal_app": APP_NAME, "power_boundary": "GPU package (NVML)"},
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
        session.flush()
        run = Run(
            run_id=run_id,
            target_id=target.target_id,
            task_id=task.task_id,
            started_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=float(remote["duration_s"])),
            finished_at=dt.datetime.now(dt.UTC),
            status="completed" if accuracy["pass"] and not partial else "failed",
            corpus_tag="X",
            warmup_count=8,
            measurement_count=int(remote["measurement_count"]),
            signal_bench_version=__version__,
            runtime_name=str(remote["runtime_name"]),
            runtime_version=str(remote["runtime_version"]),
            model_name=workload.model.name,
            model_hash=model_hash,
            quantization="float32",
            notes="Curve Fan-Out Brief A2 Modal A10G float X-corpus run.",
            telemetry_partial=partial,
            telemetry_partial_sources=partial_sources or None,
            partial_reasons=["nvml coverage/energy incomplete"] if partial else None,
            extra={
                "protocol": "curve-fanout-briefA2",
                "adapter": "ModalA10GOrtCudaAdapter",
                "model_path": str(workload.model),
                "input_data": str(workload.input_data),
                "input_sha256": input_hash,
                "power_boundary": "GPU package (NVML)",
                "lineage": {
                    "metric": workload.lineage_metric,
                    "value": workload.lineage_value,
                    "tolerance": workload.parity_tolerance,
                    "eval_note": workload.eval_note,
                },
                "run_metadata": {
                    key: remote[key]
                    for key in (
                        "runtime_name",
                        "runtime_version",
                        "execution_provider",
                        "active_providers",
                        "gpu",
                        "python",
                        "onnx_opset",
                        "input_shape",
                        "input_count",
                        "input_name",
                        "output_name",
                    )
                },
                "metrics": {
                    "latency_ms": remote["latency_ms"],
                    "accuracy_proxy": accuracy,
                    "energy": {
                        "headline_source": "nvml",
                        "headline": remote["energy"],
                        "by_source": {"nvml": remote["energy"]},
                    },
                    "telemetry": remote["telemetry"],
                    "inference_count": int(remote["measurement_count"]),
                },
                "result_rows_sampled": int(remote["result_rows_sampled"]),
            },
        )
        session.add(run)
        for sample in remote["power_samples"]:
            session.add(
                TelemetrySample(
                    run_id=run_id,
                    timestamp=dt.datetime.fromisoformat(sample["timestamp"]),
                    source="nvml",
                    metric="power",
                    value=float(sample["power_w"]),
                ),
            )
        for row in remote["result_rows"]:
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
                    accuracy_value=accuracy["value"],
                    wh_per_inference=(
                        (remote["energy"]["wh_per_1000_inferences"] / 1000.0)
                        if remote["energy"]["wh_per_1000_inferences"] is not None
                        else None
                    ),
                    extra={
                        "data_index": int(row["data_index"]),
                        "output": row["output"],
                        "sampled_result_rows": True,
                    },
                ),
            )
        session.commit()

    public_metadata = {
        key: value for key, value in remote.items() if key not in {"power_samples", "result_rows"}
    }
    return {
        "run_id": run_id,
        "task": workload.task_id,
        "status": "pass" if accuracy["pass"] and not partial else "fail",
        "latency_ms": remote["latency_ms"],
        "accuracy_proxy": accuracy,
        "energy": remote["energy"],
        "telemetry": remote["telemetry"],
        "metadata": public_metadata,
    }


def _ensure_database(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

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


if __name__ == "__main__":
    raise SystemExit(main())
