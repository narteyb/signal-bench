# SPDX-License-Identifier: Apache-2.0
"""Run P4 Hailo-10H first-light inference with host-side telemetry capture.

The HailoRT inference code runs on the Pi over SSH; telemetry stays on the Mac
and is captured through the same orchestrator/source contract used by the MCU
matrix. This is a plumbing validation against a prebuilt HEF, not an X-corpus
curve datapoint.

Requires key-based SSH to ``--host``; this public script does not carry
password-based SSH credentials.
"""

# ruff: noqa: RUF007

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import os
import shlex
import statistics
import subprocess
import sys
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
DB_PATH = ROOT / "data" / "p4_hailo_first_light.db"
REPORT_PATH = ROOT / "reports" / "p4_hailo_adapter.md"
FNB58_ADDRESS = "<fnb58-address>"
DEFAULT_HOST = "<ssh-user>@<private-ip>"
DEFAULT_REMOTE_ROOT = "signal-bench-p4-hailo"
SSH_OPTS = ["-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2"]
TASK_NAME = "hailo-prebuilt-classification"
TASK_VERSION = "p4-first-light-v1"


@dataclass(frozen=True, slots=True)
class RemoteInferenceResult:
    """Result row parsed from the Pi-side JSONL output."""

    iter_id: int
    duration_us: int
    timestamp: dt.datetime
    output: dict[str, Any]
    error: str | None


@dataclass(frozen=True, slots=True)
class RemoteRunOutput:
    """Structured output from one Pi-side HailoAdapter invocation."""

    metadata: dict[str, Any]
    results: list[RemoteInferenceResult]
    stderr: str
    measurement_complete: bool


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--hef", help="Remote .hef path. If omitted, the script selects one.")
    parser.add_argument("--local-hef", type=Path)
    parser.add_argument("--input-data", type=Path)
    parser.add_argument("--hef-source")
    parser.add_argument("--task-name", default=TASK_NAME)
    parser.add_argument("--task-version", default=TASK_VERSION)
    parser.add_argument("--task-family", default="classification")
    parser.add_argument("--protocol", default="p4-hailo-first-light")
    parser.add_argument("--quantization", default="prebuilt-hef")
    parser.add_argument(
        "--notes", default="P4 HailoAdapter first light; plumbing only, not curve-comparable."
    )
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--measurement-s", type=float, default=30.0)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--probe-iterations", type=int, default=8)
    parser.add_argument("--max-iterations", type=int, default=50_000)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--input-format-type", default="FLOAT32")
    parser.add_argument("--output-format-type", default="UINT8")
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    parser.add_argument("--fnb58-address", default=FNB58_ADDRESS)
    parser.add_argument("--fnb58-malformed-limit", type=int, default=20)
    parser.add_argument("--no-fnb58", action="store_true")
    parser.add_argument("--no-ina219", action="store_true")
    parser.add_argument("--no-bme280", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


async def _main_async(args: argparse.Namespace) -> int:
    _configure_telemetry_env()
    run_id = new_id()
    remote_root = f"{args.remote_root}-{run_id}"
    remote_results = f"{remote_root}/results.jsonl"

    _ensure_database(args.db)
    engine = create_engine(f"sqlite:///{args.db}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    r1 = _capture_r1(args.host)
    _deploy_remote(args.host, remote_root)
    hef_path, hef_source = _stage_hef(args, remote_root)
    input_data_path = _stage_input_data(args, remote_root)
    hef_sha256 = _remote_capture(args.host, f"sha256sum {shlex.quote(hef_path)}").split()[0]

    probe = await _run_remote_device(
        args,
        run_id=f"{run_id}-probe",
        remote_root=remote_root,
        remote_results=f"{remote_root}/probe-results.jsonl",
        hef_path=hef_path,
        hef_source=hef_source,
        input_data_path=input_data_path,
        iterations=args.probe_iterations,
        telemetry=None,
    )
    probe_durations = [result.duration_us for result in probe.results if result.error is None]
    if not probe_durations:
        msg = f"Hailo probe returned no successful results. stderr:\n{probe.stderr}"
        raise RuntimeError(msg)
    iterations = args.iterations or _planned_iterations(
        statistics.fmean(probe_durations),
        args.measurement_s,
        args.max_iterations,
    )

    target, task = _ensure_target_task(session_factory, args, r1)
    _create_run(
        session_factory,
        run_id,
        target,
        task,
        iterations,
        hef_path,
        hef_source,
        hef_sha256,
        probe.metadata,
        args,
    )

    telemetry = TelemetryOrchestrator(session_factory)
    telemetry_state = OrchestratorState()
    remote = RemoteRunOutput(metadata={}, results=[], stderr="", measurement_complete=False)
    try:
        await telemetry.start_run(run_id, _telemetry_sources(args))
        remote = await _run_remote_device(
            args,
            run_id=run_id,
            remote_root=remote_root,
            remote_results=remote_results,
            hef_path=hef_path,
            hef_source=hef_source,
            input_data_path=input_data_path,
            iterations=iterations,
            telemetry=telemetry,
        )
        telemetry_state = telemetry.state
    except Exception as exc:
        _mark_run_failed(session_factory, run_id, str(exc))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            _failure_report(run_id, hef_path, hef_source, r1, str(exc)),
            encoding="utf-8",
        )
        raise
    finally:
        if not remote.measurement_complete:
            telemetry_state = await telemetry.stop_run()
        if not args.no_cleanup:
            _remote_capture(args.host, f"rm -rf {shlex.quote(remote_root)}", check=False)

    _write_results(session_factory, run_id, remote.results)
    _finish_run(session_factory, run_id, remote.results, remote.metadata, telemetry_state)
    metrics = _run_metrics(session_factory, run_id, remote.results, args)
    _write_report(
        args.report,
        run_id,
        r1,
        hef_path,
        hef_source,
        hef_sha256,
        probe,
        remote,
        metrics,
        telemetry_state,
    )
    print(json.dumps({"run_id": run_id, "iterations": len(remote.results), "metrics": metrics}))
    return 0


def _configure_telemetry_env() -> None:
    os.environ.setdefault("BLINKA_MCP2221", "1")
    os.environ.setdefault("SIGNAL_BENCH_REAL_I2C", "1")
    os.environ.setdefault("FNB58_TRANSPORT", "ble")


def _capture_r1(host: str) -> dict[str, str]:
    command = (
        "printf 'kernel='; uname -r; "
        "printf 'hailort='; hailortcli --version; "
        "printf 'pyhailort='; python3 -c \"import hailo_platform; "
        'print(hailo_platform.__version__)"; '
        "printf 'dev='; ls -la /dev/hailo0; "
        "printf 'identify<<EOF\\n'; hailortcli fw-control identify; printf '\\nEOF\\n'; "
        "printf 'pcie<<EOF\\n'; sudo -n lspci -nnvvv -s 0001:01:00.0 | "
        "grep -E 'LnkSta:|Hailo|Co-processor|1e60'; printf '\\nEOF\\n'"
    )
    return {"host": host, "output": _remote_capture(host, command)}


def _select_hef(
    host: str, explicit_hef: str | None, explicit_source: str | None
) -> tuple[str, str]:
    if explicit_hef is not None:
        _remote_capture(host, f"test -f {shlex.quote(explicit_hef)}")
        source = explicit_source or _hef_source(host, explicit_hef)
        return explicit_hef, source

    find_command = "find /usr/share /opt <remote-home> -type f -iname '*.hef' 2>/dev/null | sort"
    candidates = [
        line.strip()
        for line in _remote_capture(host, find_command, check=False).splitlines()
        if line.strip()
    ]
    if not candidates:
        msg = "No prebuilt .hef found on the Pi; pass --hef with a remote Hailo-10H HEF path."
        raise RuntimeError(msg)
    selected = sorted(candidates, key=_hef_rank)[0]
    return selected, explicit_source or _hef_source(host, selected)


def _hef_rank(path: str) -> tuple[int, str]:
    lower = path.lower()
    score = 100
    if "resnet" in lower:
        score -= 40
    if "mobilenet" in lower:
        score -= 30
    if "class" in lower or "imagenet" in lower:
        score -= 20
    if "hailo10h" in lower or "h10" in lower:
        score -= 10
    if any(term in lower for term in ("yolo", "seg", "pose", "depth")):
        score += 50
    return score, path


def _hef_source(host: str, hef_path: str) -> str:
    owner = _remote_capture(host, f"dpkg -S {shlex.quote(hef_path)}", check=False).strip()
    if owner:
        return f"Model-Zoo-prebuilt on Pi; remote path {hef_path}; package owner: {owner}"
    return f"Model-Zoo-prebuilt on Pi; remote path {hef_path}; package owner not found"


def _stage_hef(args: argparse.Namespace, remote_root: str) -> tuple[str, str]:
    if args.local_hef is None:
        return _select_hef(args.host, args.hef, args.hef_source)
    if not args.local_hef.exists():
        msg = f"Local HEF not found: {args.local_hef}"
        raise RuntimeError(msg)
    remote_hef = f"{remote_root}/models/{args.local_hef.name}"
    _copy_local_file_to_remote(args.host, args.local_hef, remote_hef)
    source = args.hef_source or f"P4 Brief 2 X-corpus DFC 5.3.0 HAILO10H; local {args.local_hef}"
    return remote_hef, source


def _stage_input_data(args: argparse.Namespace, remote_root: str) -> str:
    if args.input_data is None:
        return "/dev/null"
    if not args.input_data.exists():
        msg = f"Input data not found: {args.input_data}"
        raise RuntimeError(msg)
    remote_input = f"{remote_root}/inputs/{args.input_data.name}"
    _copy_local_file_to_remote(args.host, args.input_data, remote_input)
    return remote_input


def _copy_local_file_to_remote(host: str, local_path: Path, remote_path: str) -> None:
    _remote_capture(host, f"mkdir -p {shlex.quote(str(Path(remote_path).parent))}")
    with local_path.open("rb") as handle:
        process = subprocess.run(
            [*_ssh_prefix(), host, f"cat > {shlex.quote(remote_path)}"],
            stdin=handle,
            text=False,
            capture_output=True,
            check=False,
        )
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"remote file copy failed: {stderr}")


def _deploy_remote(host: str, remote_root: str) -> None:
    _remote_capture(
        host, f"rm -rf {shlex.quote(remote_root)} && mkdir -p {shlex.quote(remote_root)}"
    )
    tar = subprocess.Popen(
        [
            "tar",
            "-C",
            str(ROOT),
            "-czf",
            "-",
            "src/signal_bench",
            "scripts/p4_hailo_device_infer.py",
        ],
        stdout=subprocess.PIPE,
    )
    try:
        ssh = subprocess.run(
            [*_ssh_prefix(), host, f"tar -xzf - -C {shlex.quote(remote_root)}"],
            stdin=tar.stdout,
            text=False,
            capture_output=True,
            check=False,
        )
    finally:
        if tar.stdout is not None:
            tar.stdout.close()
    tar_status = tar.wait()
    if tar_status != 0:
        msg = f"local tar failed with exit {tar_status}"
        raise RuntimeError(msg)
    if ssh.returncode != 0:
        msg = ssh.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"remote deploy failed: {msg}")


async def _run_remote_device(
    args: argparse.Namespace,
    *,
    run_id: str,
    remote_root: str,
    remote_results: str,
    hef_path: str,
    hef_source: str,
    input_data_path: str,
    iterations: int,
    telemetry: TelemetryOrchestrator | None,
) -> RemoteRunOutput:
    quoted = " ".join(
        [
            f"PYTHONPATH={shlex.quote(remote_root + '/src')}",
            "python3",
            shlex.quote(f"{remote_root}/scripts/p4_hailo_device_infer.py"),
            "--hef",
            shlex.quote(hef_path),
            "--hef-source",
            shlex.quote(hef_source),
            "--input-data",
            shlex.quote(input_data_path),
            "--task-id",
            shlex.quote(args.task_name),
            "--task-family",
            shlex.quote(args.task_family),
            "--quantization",
            shlex.quote(args.quantization),
            "--run-id",
            shlex.quote(run_id),
            "--iterations",
            str(iterations),
            "--batch-size",
            str(args.batch_size),
            "--input-format-type",
            shlex.quote(args.input_format_type),
            "--output-format-type",
            shlex.quote(args.output_format_type),
            "--timeout-ms",
            str(args.timeout_ms),
            "--results-jsonl",
            shlex.quote(remote_results),
        ],
    )
    process = await asyncio.create_subprocess_exec(
        *_ssh_prefix(),
        args.host,
        quoted,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    metadata: dict[str, Any] = {}
    measurement_complete = False
    assert process.stdout is not None
    while line_bytes := await process.stdout.readline():
        payload = json.loads(line_bytes.decode("utf-8"))
        if payload.get("type") == "metadata":
            metadata.update(payload["metadata"])
        elif payload.get("type") == "measurement_complete":
            measurement_complete = True
            if telemetry is not None:
                await telemetry.stop_run()
                telemetry = None

    stderr_bytes = await process.stderr.read() if process.stderr is not None else b""
    returncode = await process.wait()
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if telemetry is not None:
        await telemetry.stop_run()
    if returncode != 0:
        msg = f"remote Hailo run failed with exit {returncode}: {stderr}"
        raise RuntimeError(msg)
    results_text = _remote_capture(args.host, f"cat {shlex.quote(remote_results)}")
    return RemoteRunOutput(
        metadata=metadata,
        results=_parse_results(results_text),
        stderr=stderr,
        measurement_complete=measurement_complete,
    )


def _parse_results(text: str) -> list[RemoteInferenceResult]:
    results: list[RemoteInferenceResult] = []
    for line in text.splitlines():
        payload = json.loads(line)
        timestamp = dt.datetime.fromisoformat(payload["timestamp"])
        results.append(
            RemoteInferenceResult(
                iter_id=int(payload["iter_id"]),
                duration_us=int(payload["duration_us"]),
                timestamp=timestamp,
                output=dict(payload["output"]),
                error=payload["error"],
            ),
        )
    return results


def _planned_iterations(mean_us: float, measurement_s: float, max_iterations: int) -> int:
    estimated = math.ceil(measurement_s * 1_000_000 / max(mean_us, 1.0))
    return max(1, min(max_iterations, estimated))


def _telemetry_sources(args: argparse.Namespace) -> list[TelemetrySource]:
    sources: list[TelemetrySource] = []
    if not args.no_ina219:
        sources.append(Ina219Source(Ina219Config(address=0x40)))
    if not args.no_bme280:
        sources.append(Bme280Source(Bme280Config(address=0x77)))
    if not args.no_fnb58:
        sources.append(
            FnirsiSource(
                FnirsiSourceConfig(
                    address=args.fnb58_address,
                    malformed_limit=args.fnb58_malformed_limit,
                ),
            ),
        )
    if not sources:
        msg = "at least one telemetry source must be enabled"
        raise ValueError(msg)
    return sources


def _ensure_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/signal_bench/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _ensure_target_task(
    session_factory: sessionmaker[Session],
    args: argparse.Namespace,
    r1: dict[str, str],
) -> tuple[Target, Task]:
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == "pi5-hailo10h", Target.kind == "npu"),
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name="pi5-hailo10h",
                kind="npu",
                cpu="Raspberry Pi 5",
                accelerator="Hailo-10H",
                os_name="Raspberry Pi OS",
                extra={"host": args.host, "r1": r1},
            )
            session.add(target)
        task = session.scalar(
            select(Task).where(Task.name == args.task_name, Task.version == args.task_version),
        )
        if task is None:
            task = Task(
                task_id=new_id(),
                name=args.task_name,
                version=args.task_version,
                family=args.task_family,
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
    iterations: int,
    hef_path: str,
    hef_source: str,
    hef_sha256: str,
    probe_metadata: dict[str, Any],
    args: argparse.Namespace,
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
                warmup_count=1,
                measurement_count=iterations,
                signal_bench_version=__version__,
                runtime_name="HailoRT",
                runtime_version=str(probe_metadata.get("hailort_version", "unknown")),
                model_name=Path(hef_path).name,
                model_hash=hef_sha256,
                quantization=args.quantization,
                notes=args.notes,
                extra={
                    "protocol": args.protocol,
                    "adapter": "HailoAdapter",
                    "hef_path": hef_path,
                    "hef_source": hef_source,
                    "brief_scope": args.notes,
                    "required_metadata": probe_metadata,
                    "input_data": str(args.input_data) if args.input_data is not None else None,
                },
                telemetry_partial=False,
            ),
        )
        session.commit()


def _write_results(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[RemoteInferenceResult],
) -> None:
    with session_factory() as session:
        for result in results:
            duration_ms = result.duration_us / 1000.0
            session.add(
                Result(
                    result_id=new_id(),
                    run_id=run_id,
                    sequence=result.iter_id,
                    started_at=result.timestamp,
                    duration_ms=duration_ms,
                    throughput_unit="inferences/s",
                    throughput_value=1000 / duration_ms if duration_ms > 0 else None,
                    accuracy_value=None,
                    extra={"output": result.output, "error": result.error},
                ),
            )
        session.commit()


def _finish_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[RemoteInferenceResult],
    metadata: dict[str, Any],
    telemetry_state: OrchestratorState,
) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        extra = dict(run.extra or {}) if run is not None else {}
        extra["run_metadata"] = metadata
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
                measurement_count=len(results),
                runtime_version=str(metadata.get("hailort_version", "unknown")),
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
            .values(finished_at=dt.datetime.now(dt.UTC), status="failed", extra=extra),
        )
        session.commit()


def _run_metrics(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[RemoteInferenceResult],
    args: argparse.Namespace,
) -> dict[str, Any]:
    durations = [result.duration_us / 1000.0 for result in results if result.error is None]
    return {
        "latency_ms": {
            "mean": statistics.fmean(durations) if durations else None,
            "p50": statistics.median(durations) if durations else None,
            "p99": _percentile(durations, 99) if durations else None,
        },
        "inference_count": len(durations),
        "output_sanity": _output_sanity(results),
        "accuracy_proxy": _accuracy_proxy(results, args),
        "telemetry": _telemetry_counts(session_factory, run_id),
        "energy": _energy_metrics(session_factory, run_id, len(durations)),
    }


def _accuracy_proxy(
    results: list[RemoteInferenceResult], args: argparse.Namespace
) -> dict[str, Any] | None:
    if args.input_data is None:
        return None
    import numpy as np

    archive = np.load(args.input_data, allow_pickle=False)
    inputs = archive["inputs"].astype(np.float32)
    labels = archive["labels"].astype(np.int64) if "labels" in archive else None
    sources = archive["sources"].astype(str) if "sources" in archive else None
    outputs = [result.output for result in results if result.error is None]
    if not outputs:
        return {"status": "fail", "reason": "no successful outputs"}
    if args.task_family in {"classification", "keyword_spotting"}:
        if labels is None:
            return {"status": "fail", "reason": "labels missing"}
        predictions = np.array([int(output["argmax"]) for output in outputs], dtype=np.int64)
        truth = np.array(
            [labels[index % len(labels)] for index in range(len(predictions))], dtype=np.int64
        )
        return {
            "metric": "top1",
            "value": float(np.mean(predictions == truth)),
            "samples": len(predictions),
            "unique_predictions": len(set(predictions.tolist())),
        }
    if args.task_family == "anomaly_detection":
        if labels is None:
            return {"status": "fail", "reason": "labels missing"}
        scores = []
        truth = []
        source_keys = []
        for index, output in enumerate(outputs):
            values = np.asarray(output.get("values", []), dtype=np.float32).reshape(-1)
            sample = inputs[index % len(inputs)].reshape(-1)
            if values.shape != sample.shape:
                return {
                    "status": "fail",
                    "reason": f"output shape {values.shape} does not match input shape {sample.shape}",
                }
            scores.append(float(np.mean((values - sample) ** 2)))
            truth.append(int(labels[index % len(labels)]))
            if sources is not None:
                source_keys.append(str(sources[index % len(sources)]))
        if source_keys:
            grouped_scores: dict[str, list[float]] = {}
            grouped_truth: dict[str, int] = {}
            for source, label, score in zip(source_keys, truth, scores, strict=True):
                grouped_scores.setdefault(source, []).append(score)
                grouped_truth.setdefault(source, label)
            clip_scores = [
                float(np.mean(values)) for _source, values in sorted(grouped_scores.items())
            ]
            clip_truth = [grouped_truth[source] for source in sorted(grouped_scores)]
            return {
                "metric": "clip_auroc",
                "value": _binary_auc(np.asarray(clip_truth), np.asarray(clip_scores)),
                "samples": len(scores),
                "groups": len(clip_scores),
                "mean_score": float(np.mean(clip_scores)),
            }
        return {
            "metric": "auroc",
            "value": _binary_auc(np.asarray(truth), np.asarray(scores)),
            "samples": len(scores),
            "mean_score": float(np.mean(scores)),
        }
    return {"status": "unknown", "family": args.task_family}


def _binary_auc(labels: object, scores: object) -> float | None:
    import numpy as np

    y = np.asarray(labels, dtype=np.int64)
    s = np.asarray(scores, dtype=np.float64)
    positives = y == 1
    negatives = y == 0
    n_pos = int(positives.sum())
    n_neg = int(negatives.sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(s)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(s) + 1, dtype=np.float64)
    pos_rank_sum = float(ranks[positives].sum())
    return (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _output_sanity(results: list[RemoteInferenceResult]) -> dict[str, Any]:
    outputs = [result.output for result in results if result.error is None]
    argmaxes = [output.get("argmax") for output in outputs if "argmax" in output]
    return {
        "valid_outputs": len(outputs),
        "unique_argmax_count": len(set(argmaxes)),
        "first_output": outputs[0] if outputs else None,
        "garbage": not outputs,
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
    grouped = {source: max(metrics.values()) for source, metrics in by_source.items()}
    return {
        "grouped_instants": grouped,
        "rows": by_source,
        "partial": bool(run.telemetry_partial) if run is not None else True,
        "partial_sources": list(run.telemetry_partial_sources or []) if run is not None else [],
    }


def _energy_metrics(
    session_factory: sessionmaker[Session],
    run_id: str,
    inference_count: int,
) -> dict[str, Any]:
    if inference_count <= 0:
        return {"source": None, "wh_per_1000_inferences": None, "avg_power_w": None}
    candidates = [
        _wh_per_1000_from_source(session_factory, run_id, source, inference_count)
        for source in ("ina219", "fnb58")
    ]
    valid = [
        candidate
        for candidate in candidates
        if candidate["wh_per_1000_inferences"] is not None
        and candidate["avg_power_w"] is not None
        and candidate["avg_power_w"] > 0.05
    ]
    if valid:
        return max(valid, key=lambda candidate: candidate["avg_power_w"] or 0.0)
    return candidates[0]


def _wh_per_1000_from_source(
    session_factory: sessionmaker[Session],
    run_id: str,
    source: str,
    inference_count: int,
) -> dict[str, Any]:
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
        return {"source": source, "wh_per_1000_inferences": None, "avg_power_w": None}
    joules = 0.0
    total_s = 0.0
    for previous, current in zip(samples, samples[1:], strict=False):
        dt_s = (current.timestamp - previous.timestamp).total_seconds()
        if dt_s > 0:
            joules += ((previous.value + current.value) / 2.0) * dt_s
            total_s += dt_s
    wh_per_1000 = joules / 3600.0 / inference_count * 1000.0
    avg_power = joules / total_s if total_s > 0 else None
    return {
        "source": source,
        "wh_per_1000_inferences": wh_per_1000,
        "avg_power_w": avg_power,
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _write_report(
    report_path: Path,
    run_id: str,
    r1: dict[str, str],
    hef_path: str,
    hef_source: str,
    hef_sha256: str,
    probe: RemoteRunOutput,
    remote: RemoteRunOutput,
    metrics: dict[str, Any],
    telemetry_state: OrchestratorState,
) -> None:
    metadata = remote.metadata or probe.metadata
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(
            [
                "# P4 HailoAdapter First Light",
                "",
                "## Summary",
                f"1. Result: {'PASS' if not metrics['telemetry']['partial'] else 'FAIL'} for plumbing; NOT curve-comparable until Brief 2 X-corpus compile.",
                f"2. NPU/runtime: {metadata.get('hailo_architecture', 'unknown')} / HailoRT {metadata.get('hailort_version', 'unknown')} / firmware {metadata.get('hailo_firmware_version', 'unknown')}.",
                f"3. Kernel/PCIe: {metadata.get('kernel_version', 'unknown')} / {metadata.get('pcie_link', 'unknown')}.",
                f"4. HEF: `{Path(hef_path).name}` from {hef_source}; sha256 `{hef_sha256}`.",
                f"5. Run: `{run_id}`, {metrics['inference_count']} inferences, energy `{metrics['energy']}`.",
                f"6. Telemetry: {metrics['telemetry']}; partial reasons: {telemetry_state.partial_reasons}.",
                "",
                "## R1 Recon",
                "",
                "```text",
                r1["output"].strip(),
                "```",
                "",
                "## Adapter Contract",
                "",
                "- Adapter methods matched existing `Adapter`: `prepare(run_id)`, `warmup()`, `measure(task, iterations)`, `read_thermal()`, `os_info()`, `teardown()`.",
                "- Telemetry uses the existing async source contract: `start()`, `samples()` async iterator, `stop()`, grouped `TelemetrySample.values`.",
                "- DB writes use existing `runs`, `results`, `telemetry_samples`, `targets`, and `tasks`; telemetry column is `metric`.",
                "",
                "## Run Metadata",
                "",
                "```json",
                json.dumps(metadata, indent=2, sort_keys=True),
                "```",
                "",
                "## Metrics",
                "",
                "```json",
                json.dumps(metrics, indent=2, sort_keys=True),
                "```",
                "",
                "## First Output",
                "",
                "```json",
                json.dumps(metrics["output_sanity"].get("first_output"), indent=2, sort_keys=True),
                "```",
                "",
                "## Scope Flag",
                "",
                "Plumbing proven only. This run uses a prebuilt classification HEF and is not curve-comparable. Brief 2 must compile the X-corpus IC/KWS/AD models to HEF before the NPU lands on the hardware curve.",
                "",
            ],
        ),
        encoding="utf-8",
    )


def _failure_report(
    run_id: str,
    hef_path: str,
    hef_source: str,
    r1: dict[str, str],
    error: str,
) -> str:
    return "\n".join(
        [
            "# P4 HailoAdapter First Light",
            "",
            "## Summary",
            "1. Result: FAIL.",
            "2. NPU/runtime: see R1 output below.",
            "3. Kernel/PCIe: see R1 output below.",
            f"4. HEF: `{Path(hef_path).name}` from {hef_source}.",
            f"5. Run: `{run_id}` did not complete.",
            f"6. Error: {error}",
            "",
            "## R1 Recon",
            "",
            "```text",
            r1["output"].strip(),
            "```",
            "",
        ],
    )


def _remote_capture(host: str, command_text: str, *, check: bool = True) -> str:
    process = subprocess.run(
        [*_ssh_prefix(), host, command_text],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (process.stdout or "") + (process.stderr or "")
    if check and process.returncode != 0:
        raise RuntimeError(output.strip() or f"ssh command failed with exit {process.returncode}")
    return output


def _ssh_prefix() -> list[str]:
    return ["ssh", *SSH_OPTS]


if __name__ == "__main__":
    sys.exit(main())
