# SPDX-License-Identifier: Apache-2.0
"""Run Curve Fan-Out Brief B Jetson Orin Nano X-corpus measurements.

Requires key-based SSH to ``--host`` and passwordless remote sudo for
``jetson_clocks`` / ``jetson_clocks --show``.
"""


from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import modal

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curve_fanout_briefB.db"
REPORT_JSON = ROOT / "reports" / "scratch" / "curve_jetson_results.json"
ONNX_ROOT = Path("<local-path>")
REMOTE_ROOT = "<remote-home>"
DEFAULT_HOST = "<ssh-user>@<private-ip>"
APP_NAME = "signal-bench-jetson-convert"
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


image = (
    modal.Image.from_registry("ubuntu:22.04", add_python="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(
        "numpy==1.26.4",
        "onnx==1.17.0",
        "tensorflow-cpu==2.16.1",
        "tf2onnx==1.16.1",
    )
)
app = modal.App(APP_NAME)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--remote-root", default=REMOTE_ROOT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--duration-s", type=float, default=35.0)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--max-result-rows", type=int, default=200_000)
    parser.add_argument("--only", choices=["ic", "kws", "ad"], action="append")
    parser.add_argument("--results-json", type=Path, default=REPORT_JSON)
    args = parser.parse_args()
    return _run(args)


@app.local_entrypoint()
def modal_main(
    host: str = DEFAULT_HOST,
    remote_root: str = REMOTE_ROOT,
    db: str = str(DB_PATH),
    duration_s: float = 35.0,
    warmup: int = 8,
    max_result_rows: int = 200_000,
    only: str = "",
    results_json: str = str(REPORT_JSON),
) -> None:
    selected = [item.strip() for item in only.split(",") if item.strip()] or None
    args = argparse.Namespace(
        host=host,
        remote_root=remote_root,
        db=Path(db),
        duration_s=duration_s,
        warmup=warmup,
        max_result_rows=max_result_rows,
        only=selected,
        results_json=Path(results_json),
    )
    raise SystemExit(_run(args))


def _run(args: argparse.Namespace) -> int:
    _ensure_database(args.db)
    r1 = _capture_r1(args.host)
    _remote_capture(
        args.host,
        f"mkdir -p {shlex.quote(args.remote_root)} {shlex.quote(args.remote_root + '/models')} {shlex.quote(args.remote_root + '/inputs')} {shlex.quote(args.remote_root + '/scripts')}",
    )
    _write_remote_runner(args.host, args.remote_root)
    _remote_sudo(args.host, "jetson_clocks")
    clocks_before = _remote_sudo_capture(args.host, "jetson_clocks --show")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{args.db}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    summaries = []
    workloads = [item for item in _workloads() if not args.only or item.task_id in set(args.only)]
    for workload in workloads:
        onnx_path = _convert_to_onnx(workload)
        remote_model = f"{args.remote_root}/models/{onnx_path.name}"
        remote_input = f"{args.remote_root}/inputs/{workload.input_data.name}"
        _scp_to(args.host, onnx_path, remote_model)
        _scp_to(args.host, workload.input_data, remote_input)
        remote = _run_remote_workload(args, workload, remote_model, remote_input)
        clocks_after = _remote_sudo_capture(args.host, "jetson_clocks --show")
        summary = _record_run(
            session_factory, workload, remote, onnx_path, r1, clocks_before, clocks_after
        )
        summaries.append(summary)
        print(json.dumps({"task": workload.task_id, "summary": summary}, sort_keys=True))

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(
        json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


@app.function(image=image, timeout=1800)
def convert_tflite_to_onnx(task_id: str, model_bytes: bytes) -> dict[str, Any]:
    work_dir = Path(tempfile.mkdtemp(prefix=f"signal-bench-jetson-convert-{task_id}-"))
    model_path = work_dir / f"{task_id}.tflite"
    onnx_path = work_dir / f"{task_id}.onnx"
    model_path.write_bytes(model_bytes)
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
    return {
        "onnx": onnx_path.read_bytes(),
        "stdout_tail": converted.stdout[-2000:],
        "stderr_tail": converted.stderr[-2000:],
    }


def _workloads() -> list[Workload]:
    base = Path("<local-path>")
    return [
        Workload(
            "ic",
            "classification",
            "x-corpus-ic-float-jetson",
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
            "x-corpus-kws-float-jetson",
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
            "x-corpus-ad-float-jetson",
            base / "ad" / "ad_float.tflite",
            base / "ad" / "eval_clip_frames.npz",
            "clip_auroc",
            0.8391,
            0.03,
            "Deterministic balanced clip-level frame set from P4 compile inputs.",
        ),
    ]


def _convert_to_onnx(workload: Workload) -> Path:
    ONNX_ROOT.mkdir(parents=True, exist_ok=True)
    output = ONNX_ROOT / f"{workload.task_id}.onnx"
    if output.exists() and output.stat().st_mtime >= workload.model.stat().st_mtime:
        return output
    remote = convert_tflite_to_onnx.remote(workload.task_id, workload.model.read_bytes())
    output.write_bytes(remote["onnx"])
    (ONNX_ROOT / f"{workload.task_id}.convert.json").write_text(
        json.dumps(
            {key: value for key, value in remote.items() if key != "onnx"}, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def _run_remote_workload(
    args: argparse.Namespace,
    workload: Workload,
    remote_model: str,
    remote_input: str,
) -> dict[str, Any]:
    command = " ".join(
        [
            "~/venvs/edge/bin/python",
            shlex.quote(f"{args.remote_root}/scripts/curve_jetson_ort_device.py"),
            "--model",
            shlex.quote(remote_model),
            "--input-data",
            shlex.quote(remote_input),
            "--task-id",
            shlex.quote(workload.task_id),
            "--task-family",
            shlex.quote(workload.family),
            "--duration-s",
            str(args.duration_s),
            "--warmup",
            str(args.warmup),
            "--max-result-rows",
            str(args.max_result_rows),
        ],
    )
    text = _remote_capture(args.host, command, timeout_s=3600)
    return json.loads(text)


def _capture_r1(host: str) -> dict[str, str]:
    return {
        "host": host,
        "identity": _remote_capture(
            host,
            "hostname; hostname -I; uname -a; cat /etc/nv_tegra_release; cat /etc/os-release | head -8",
        ),
        "runtime": _remote_capture(
            host,
            "~/venvs/edge/bin/python - <<'PY'\nimport onnxruntime as ort\nprint(ort.__version__)\nprint(ort.get_available_providers())\nPY",
        ),
        "power_path": _remote_capture(
            host,
            'cat /sys/class/hwmon/hwmon*/name 2>/dev/null; for f in /sys/class/hwmon/hwmon*/in*_label; do [ -e "$f" ] && printf "%s=" "$f" && cat "$f"; done',
        ),
    }


def _record_run(
    session_factory: Any,
    workload: Workload,
    remote: dict[str, Any],
    onnx_path: Path,
    r1: dict[str, str],
    clocks_before: str,
    clocks_after: str,
) -> dict[str, Any]:
    from sqlalchemy import select

    from signal_bench import __version__
    from signal_bench.ids import new_id
    from signal_bench.schema import Result, Run, Target, Task, TelemetrySample

    run_id = new_id()
    model_hash = _sha256(onnx_path)
    input_hash = _sha256(workload.input_data)
    accuracy = dict(remote["accuracy_proxy"])
    accuracy["lineage"] = workload.lineage_value
    accuracy["delta"] = (
        accuracy["value"] - workload.lineage_value if accuracy.get("value") is not None else None
    )
    accuracy["pass"] = (
        accuracy["delta"] is not None and abs(accuracy["delta"]) <= workload.parity_tolerance
    )
    telemetry_partial = (
        bool(remote["telemetry"]["partial"]) or remote["energy"]["wh_per_1000_inferences"] is None
    )
    partial_sources = ["jetson_ina3221"] if telemetry_partial else []
    status = (
        "completed"
        if accuracy["pass"] and not telemetry_partial and remote["no_throttle"]
        else "failed"
    )

    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == "jetson-orin-nano", Target.kind == "sbc")
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name="jetson-orin-nano",
                kind="sbc",
                cpu="Jetson Orin Nano Super",
                accelerator="Ampere GPU",
                ram_mb=8192,
                os_name="Ubuntu 22.04 / Jetson Linux",
                extra={
                    "host": r1["host"],
                    "power_boundary": "whole-board (INA3221 VDD_IN)",
                    "r1": r1,
                },
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
            started_at=dt.datetime.fromisoformat(remote["started_at"]),
            finished_at=dt.datetime.fromisoformat(remote["finished_at"]),
            status=status,
            corpus_tag="X",
            warmup_count=int(remote["warmup"]),
            measurement_count=int(remote["measurement_count"]),
            signal_bench_version=__version__,
            runtime_name="onnxruntime-gpu",
            runtime_version=str(remote["runtime_version"]),
            model_name=onnx_path.name,
            model_hash=model_hash,
            quantization="float32",
            notes="Curve Fan-Out Brief B Jetson Orin Nano ORT-CUDA float X-corpus run.",
            telemetry_partial=telemetry_partial,
            telemetry_partial_sources=partial_sources or None,
            partial_reasons=(
                ["jetson_ina3221 coverage/energy incomplete"] if telemetry_partial else None
            ),
            extra={
                "protocol": "curve-fanout-briefB",
                "adapter": "JetsonOrtCudaAdapter",
                "model_path": str(onnx_path),
                "input_data": str(workload.input_data),
                "input_sha256": input_hash,
                "power_boundary": "whole-board (INA3221 VDD_IN)",
                "lineage": {
                    "metric": workload.lineage_metric,
                    "value": workload.lineage_value,
                    "tolerance": workload.parity_tolerance,
                    "eval_note": workload.eval_note,
                },
                "run_metadata": remote["metadata"],
                "metrics": {
                    "latency_ms": remote["latency_ms"],
                    "accuracy_proxy": accuracy,
                    "energy": {
                        "headline_source": "jetson_ina3221",
                        "headline": remote["energy"],
                        "by_source": {"jetson_ina3221": remote["energy"]},
                    },
                    "telemetry": remote["telemetry"],
                    "inference_count": int(remote["measurement_count"]),
                },
                "jetson_clocks": {"before": clocks_before, "after": clocks_after},
                "r1": r1,
            },
        )
        session.add(run)
        for sample in remote["power_samples"]:
            timestamp = dt.datetime.fromisoformat(sample["timestamp"])
            for metric in ("voltage", "current", "power"):
                session.add(
                    TelemetrySample(
                        run_id=run_id,
                        timestamp=timestamp,
                        source="jetson_ina3221",
                        metric=metric,
                        value=float(sample[metric]),
                    )
                )
        for sample in remote["thermal_samples"]:
            timestamp = dt.datetime.fromisoformat(sample["timestamp"])
            for metric, value in sample["values"].items():
                session.add(
                    TelemetrySample(
                        run_id=run_id,
                        timestamp=timestamp,
                        source="jetson_thermal",
                        metric=str(metric),
                        value=float(value),
                    )
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
                    throughput_value=1000.0 / duration_ms if duration_ms > 0 else None,
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

    return {
        "run_id": run_id,
        "task": workload.task_id,
        "status": "pass" if status == "completed" else "fail",
        "latency_ms": remote["latency_ms"],
        "accuracy_proxy": accuracy,
        "energy": remote["energy"],
        "telemetry": remote["telemetry"],
        "metadata": remote["metadata"],
        "no_throttle": remote["no_throttle"],
    }


def _write_remote_runner(host: str, remote_root: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False) as handle:
        handle.write(_REMOTE_RUNNER)
        local = Path(handle.name)
    try:
        _scp_to(host, local, f"{remote_root}/scripts/curve_jetson_ort_device.py")
    finally:
        local.unlink(missing_ok=True)


def _ensure_database(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/signal_bench/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _remote_capture(host: str, command: str, *, timeout_s: int = 120) -> str:
    result = subprocess.run(
        [
            "ssh",
            *SSH_OPTS,
            host,
            command,
        ],
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"remote command failed ({result.returncode}): {command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def _remote_sudo(host: str, command: str) -> None:
    _remote_sudo_capture(host, command)


def _remote_sudo_capture(host: str, command: str) -> str:
    return _remote_capture(
        host,
        f"sudo -n sh -lc {shlex.quote(command)}",
        timeout_s=300,
    )


def _scp_to(host: str, local: Path, remote: str) -> None:
    result = subprocess.run(
        [
            "scp",
            *SSH_OPTS,
            str(local),
            f"{host}:{remote}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"scp failed for {local} -> {remote}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_REMOTE_RUNNER = r"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import platform
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input-data", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task-family", required=True)
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--max-result-rows", type=int, default=200000)
    args = parser.parse_args()
    print(json.dumps(run(args), sort_keys=True))
    return 0


def run(args: argparse.Namespace) -> dict[str, Any]:
    session = ort.InferenceSession(args.model, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    active_providers = session.get_providers()
    if "CUDAExecutionProvider" not in active_providers:
        raise RuntimeError(f"CUDAExecutionProvider not active: {active_providers}")
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    archive = np.load(args.input_data, allow_pickle=False)
    inputs = archive["inputs"].astype(np.float32, copy=False)
    labels = archive["labels"].astype(np.int64, copy=False) if "labels" in archive else None
    sources = archive["sources"].astype(str, copy=False) if "sources" in archive else None

    for index in range(min(args.warmup, len(inputs))):
        session.run([output_name], {input_name: inputs[index : index + 1]})

    accuracy = accuracy_proxy(session, input_name, output_name, inputs, labels, sources, args.task_family)
    started_at = dt.datetime.now(dt.timezone.utc)
    power_samples, thermal_samples, latency, rows = measure(
        session, input_name, output_name, inputs, labels, sources, args.task_family, args.duration_s, args.max_result_rows
    )
    finished_at = dt.datetime.now(dt.timezone.utc)
    energy = energy_from_power(power_samples, latency["count"])
    metadata = {
        "runtime_name": "onnxruntime-gpu",
        "runtime_version": ort.__version__,
        "execution_provider": "CUDAExecutionProvider",
        "active_providers": active_providers,
        "python": platform.python_version(),
        "kernel": platform.release(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "jetpack_l4t": read_file("/etc/nv_tegra_release").strip(),
        "input_shape": list(inputs.shape[1:]),
        "input_count": int(inputs.shape[0]),
        "input_name": input_name,
        "output_name": output_name,
        "batch_size": 1,
        "power_boundary": "whole-board (INA3221 VDD_IN)",
    }
    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "warmup": args.warmup,
        "measurement_count": latency["count"],
        "runtime_version": ort.__version__,
        "accuracy_proxy": accuracy,
        "latency_ms": latency,
        "energy": energy,
        "telemetry": {
            "sources": {"jetson_ina3221": len(power_samples), "jetson_thermal": len(thermal_samples)},
            "partial": len(power_samples) < max(2, int(args.duration_s / 2.4 * 0.75)),
        },
        "power_samples": power_samples,
        "thermal_samples": thermal_samples,
        "result_rows": rows,
        "metadata": metadata,
        "no_throttle": True,
    }


def measure(session: Any, input_name: str, output_name: str, inputs: Any, labels: Any, sources: Any, family: str, duration_s: float, max_rows: int):
    rail = find_vdd_in()
    power_samples: list[dict[str, Any]] = []
    thermal_samples: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    durations: list[float] = []
    started_perf = time.perf_counter()
    started_wall = dt.datetime.now(dt.timezone.utc)
    next_telemetry = started_perf
    sequence = 0
    while time.perf_counter() - started_perf < duration_s:
        now = time.perf_counter()
        if now >= next_telemetry:
            timestamp = (started_wall + dt.timedelta(seconds=now - started_perf)).isoformat()
            rail_sample = read_rail(rail)
            rail_sample["timestamp"] = timestamp
            power_samples.append(rail_sample)
            thermal_samples.append({"timestamp": timestamp, "values": read_thermal()})
            next_telemetry = now + 2.4
        data_index = sequence % len(inputs)
        sample = inputs[data_index : data_index + 1]
        timestamp = started_wall + dt.timedelta(seconds=time.perf_counter() - started_perf)
        t0 = time.perf_counter_ns()
        output = session.run([output_name], {input_name: sample})[0]
        duration_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        durations.append(duration_ms)
        if len(result_rows) < max_rows:
            result_rows.append({
                "sequence": sequence,
                "data_index": int(data_index),
                "timestamp": timestamp.isoformat(),
                "duration_ms": float(duration_ms),
                "output": output_summary(output, sample, family, int(labels[data_index]) if labels is not None else None, str(sources[data_index]) if sources is not None else None),
            })
        sequence += 1
    return power_samples, thermal_samples, latency_summary(durations), result_rows


def accuracy_proxy(session: Any, input_name: str, output_name: str, inputs: Any, labels: Any, sources: Any, family: str) -> dict[str, Any]:
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
        score = float(np.mean((output.reshape(-1).astype(np.float32) - sample.reshape(-1).astype(np.float32)) ** 2))
        source = str(sources[index])
        grouped.setdefault(source, []).append(score)
        truth.setdefault(source, int(labels[index]))
    ordered = sorted(grouped)
    return {"metric": "clip_auroc", "value": binary_auc([truth[source] for source in ordered], [statistics.fmean(grouped[source]) for source in ordered]), "eval_count": len(inputs), "groups": len(ordered)}


def output_summary(output: Any, sample: Any, family: str, label: int | None, source: str | None) -> dict[str, Any]:
    values = output.reshape(-1).astype(np.float32)
    if family in {"classification", "keyword_spotting"}:
        argmax = int(np.argmax(values))
        return {"argmax": argmax, "confidence": float(values[argmax]), "label": label}
    sample_values = sample.reshape(-1).astype(np.float32)
    return {"score": float(np.mean((values - sample_values) ** 2)), "label": label, "source": source}


def find_vdd_in() -> dict[str, Path]:
    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        if read_file(hwmon / "name").strip() != "ina3221":
            continue
        for label in sorted(hwmon.glob("in*_label")):
            if read_file(label).strip() == "VDD_IN":
                index = label.name.removeprefix("in").removesuffix("_label")
                return {"voltage": hwmon / f"in{index}_input", "current": hwmon / f"curr{index}_input"}
    raise RuntimeError("VDD_IN INA3221 rail not found")


def read_rail(rail: dict[str, Path]) -> dict[str, float]:
    voltage = float(read_file(rail["voltage"])) / 1000.0
    current = float(read_file(rail["current"])) / 1000.0
    return {"voltage": voltage, "current": current, "power": voltage * current}


def read_thermal() -> dict[str, float]:
    values = {}
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            name = metric_name(read_file(zone / "type"))
            values[name] = float(read_file(zone / "temp")) / 1000.0
        except (OSError, TypeError, ValueError):
            continue
    return values


def read_file(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def metric_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_") + "_c"


def energy_from_power(power_samples: list[dict[str, Any]], count: int) -> dict[str, Any]:
    if len(power_samples) < 2 or count <= 0:
        return {"source": "jetson_ina3221", "wh_per_1000_inferences": None, "avg_power_w": None, "duration_s": None}
    joules = 0.0
    total_s = 0.0
    parsed = [(dt.datetime.fromisoformat(item["timestamp"]), float(item["power"])) for item in power_samples]
    for previous, current in zip(parsed, parsed[1:]):
        seconds = (current[0] - previous[0]).total_seconds()
        if seconds > 0:
            joules += ((previous[1] + current[1]) / 2.0) * seconds
            total_s += seconds
    return {
        "source": "jetson_ina3221",
        "wh_per_1000_inferences": joules / 3600.0 / count * 1000.0 if total_s > 0 else None,
        "avg_power_w": joules / total_s if total_s > 0 else None,
        "duration_s": total_s,
    }


def latency_summary(values: list[float]) -> dict[str, Any]:
    return {"mean": statistics.fmean(values) if values else None, "p50": statistics.median(values) if values else None, "p99": percentile(values, 99) if values else None, "count": len(values)}


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def binary_auc(labels: list[int], scores: list[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores) if label == 1]
    negatives = [score for label, score in zip(labels, scores) if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


if __name__ == "__main__":
    raise SystemExit(main())
"""


if __name__ == "__main__":
    raise SystemExit(main())
