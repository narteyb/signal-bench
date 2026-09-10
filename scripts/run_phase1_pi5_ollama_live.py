#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the canonical Phase 1 Pi 5 Ollama benchmark with live telemetry."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import getpass
import json
import math
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from signal_bench.phase1.environment import collect_environment
from signal_bench.phase1.measurement import (
    TelemetryRecorder,
    compare_dual_meter,
    integrate_joules,
    power_series_by_source,
)
from signal_bench.phase1.runtime import GenerationRequest, GenerationResult, RuntimeMetadata
from signal_bench.phase1.workload import PromptCase, canonical_llm_workload
from signal_bench.telemetry import (
    Bme280Config,
    Bme280Source,
    FnirsiSource,
    FnirsiSourceConfig,
    Ina219Config,
    Ina219Source,
    TelemetrySample,
)

DEFAULT_FNB58_ADDRESS = "<fnb58-address>"
DEFAULT_PI_HOST = "<private-ip>"
DEFAULT_PI_USER = os.environ.get("SIGNAL_BENCH_PI_USER", getpass.getuser())
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_WARMUPS = 5
DEFAULT_MEASURED = 20
DEFAULT_MAX_MEASURED_ATTEMPTS = 30
DEFAULT_TEMP_LIMIT_C = 70.0
DEFAULT_CONTEXT_LENGTH = 4096
DEFAULT_THERMAL_POLL_S = 10.0
PROTOCOL_ID = "n20_plus_5_v1"
PI5_CPU_COOLING_POLICY = (
    "Raspberry Pi Active Cooler configured in /boot/firmware/config.txt for "
    "max PWM from idle during canonical Pi 5 CPU runs: "
    "fan_temp0=35000, fan_temp1=40000, fan_temp2=45000, fan_temp3=50000, "
    "all fan_temp speeds=255."
)
RUN_ROOT = ROOT / "data" / "phase1" / "pi5-cpu" / "canonical"


def main() -> None:
    args = _parse_args()
    _set_default_blinka_env()
    environment = collect_environment(ROOT)
    command = _repro_command(args)
    run_id = f"phase1-pi5-cpu-canonical-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_root = args.output_root
    output_dir = run_root / run_id
    local_port = _free_port()

    tunnel = _start_ssh_tunnel(args, local_port)
    memory_monitor = RemoteMemoryMonitor(args)
    recorder: TelemetryRecorder | None = None
    recorder_session: AsyncRecorderSession | None = None
    try:
        base_url = f"http://127.0.0.1:{local_port}"
        _wait_for_ollama(base_url)
        pi_identity = _pi_identity(args)
        _abort_if_active_throttle(pi_identity["throttled"], "session start")
        pi_identity["clock_state"] = _capture_pi_clock_state(args)
        model_info = _require_model(base_url, args.model)
        runtime = _runtime_metadata(args, pi_identity, model_info)
        workload = canonical_llm_workload(args.model)

        sources = _live_sources(args)
        recorder = TelemetryRecorder(sources)
        recorder_session = AsyncRecorderSession(recorder)
        memory_monitor.start()
        session_started_at = dt.datetime.now(dt.UTC)
        recorder_session.start()
        invocation_rows: list[dict[str, Any]] = []

        try:
            for warmup_index in range(1, args.warmups + 1):
                invocation_rows.extend(
                    _run_task_suite(
                        args,
                        base_url,
                        workload.prompts,
                        phase="warmup",
                        phase_index=warmup_index,
                        is_warmup=True,
                        memory_monitor=memory_monitor,
                    ),
                )

            valid_measured_sessions = 0
            measured_attempt = 0
            while valid_measured_sessions < args.measured_runs:
                measured_attempt += 1
                if measured_attempt > args.max_measured_attempts:
                    raise RuntimeError(
                        "Unable to collect "
                        f"{args.measured_runs} valid measured sessions within "
                        f"{args.max_measured_attempts} attempts.",
                    )
                rows = _run_task_suite(
                    args,
                    base_url,
                    workload.prompts,
                    phase="measured",
                    phase_index=measured_attempt,
                    is_warmup=False,
                    memory_monitor=memory_monitor,
                )
                invocation_rows.extend(rows)
                if all(not row["excluded_from_stats"] for row in rows):
                    valid_measured_sessions += 1
                    print(
                        f"Measured session {valid_measured_sessions}/{args.measured_runs} "
                        f"accepted (attempt {measured_attempt}).",
                        flush=True,
                    )
                else:
                    reasons = sorted(
                        {reason for row in rows for reason in row["exclusion_reasons"]},
                    )
                    print(
                        f"Measured attempt {measured_attempt} excluded: {', '.join(reasons)}",
                        flush=True,
                    )
        finally:
            session_finished_at = dt.datetime.now(dt.UTC)
            recorder_session.stop()
            memory_monitor.stop()

        samples = recorder.samples
        _attach_measurements(invocation_rows, samples, memory_monitor.samples)
        measured_rows = [row for row in invocation_rows if _is_stats_row(row)]
        if _valid_measured_session_count(measured_rows) < args.measured_runs:
            raise RuntimeError(
                "Canonical report would contain fewer than 20 valid measured sessions."
            )

        accuracy = _classification_accuracy(measured_rows)
        report = _build_report(
            args=args,
            run_id=run_id,
            runtime=runtime,
            workload=workload,
            command=command,
            environment=environment,
            pi_identity=pi_identity,
            invocation_rows=invocation_rows,
            measured_rows=measured_rows,
            session_started_at=session_started_at,
            session_finished_at=session_finished_at,
            samples=samples,
            accuracy=accuracy,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "phase1-pi5-cpu-canonical-report.json"
        md_path = output_dir / "phase1-pi5-cpu-canonical-report.md"
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(_render_markdown(report), encoding="utf-8")
        _write_latest_pointer(run_root / "latest.json", json_path)
        print(f"Canonical JSON: {json_path}")
        print(f"Canonical Markdown: {md_path}")
    finally:
        memory_monitor.stop()
        if recorder_session is not None:
            with contextlib_suppress(Exception):
                recorder_session.stop()
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()


class contextlib_suppress:
    """Tiny local suppressor to avoid importing contextlib for one cleanup site."""

    def __init__(self, *exceptions: type[BaseException]) -> None:
        self._exceptions = exceptions or (Exception,)

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return exc_type is not None and issubclass(exc_type, self._exceptions)


class AsyncRecorderSession:
    """Run telemetry recorder start/pump/stop on one persistent event loop."""

    def __init__(self, recorder: TelemetryRecorder) -> None:
        self._recorder = recorder
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._started = False
        self._stopped = False

    def start(self) -> None:
        if self._started:
            return
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._recorder.start(), self._loop)
        future.result(timeout=30)
        self._started = True

    def stop(self) -> None:
        if not self._started or self._stopped:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._recorder.stop(), self._loop)
            future.result(timeout=30)
        finally:
            self._stopped = True
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
            self._loop.close()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()


class RemoteMemoryMonitor:
    """Poll aggregate Ollama RSS on the Pi while the session runs."""

    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.samples: list[dict[str, float]] = []

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def peak_between(self, started_at: dt.datetime, finished_at: dt.datetime) -> float | None:
        start_ts = started_at.timestamp()
        finish_ts = finished_at.timestamp()
        values = [
            sample["rss_mb"]
            for sample in self.samples
            if start_ts <= sample["timestamp_unix"] <= finish_ts
        ]
        return max(values) if values else None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                output = _ssh_text(
                    self._args,
                    (
                        "ps -eo rss=,comm= | "
                        'awk \'$2=="ollama" || $2=="llama-server" {s+=$1} END{print s+0}\''
                    ),
                    timeout=10,
                )
                rss_kb = float(output.strip() or "0")
            except Exception:
                rss_kb = 0.0
            self.samples.append({"timestamp_unix": time.time(), "rss_mb": rss_kb / 1024.0})
            self._stop.wait(1.0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-host", default=DEFAULT_PI_HOST)
    parser.add_argument("--pi-user", default=DEFAULT_PI_USER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--fnb58-address", default=DEFAULT_FNB58_ADDRESS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--measured-runs", type=int, default=DEFAULT_MEASURED)
    parser.add_argument("--max-measured-attempts", type=int, default=DEFAULT_MAX_MEASURED_ATTEMPTS)
    parser.add_argument("--temp-limit-c", type=float, default=DEFAULT_TEMP_LIMIT_C)
    parser.add_argument("--thermal-poll-s", type=float, default=DEFAULT_THERMAL_POLL_S)
    parser.add_argument("--context-length", type=int, default=DEFAULT_CONTEXT_LENGTH)
    parser.add_argument("--num-thread", type=int)
    parser.add_argument("--output-root", type=Path, default=RUN_ROOT)
    return parser.parse_args()


def _repro_command(args: argparse.Namespace) -> str:
    parts = [
        "uv",
        "run",
        "python",
        "scripts/run_phase1_pi5_ollama_live.py",
        "--pi-host",
        args.pi_host,
        "--pi-user",
        args.pi_user,
        "--model",
        args.model,
        "--warmups",
        str(args.warmups),
        "--measured-runs",
        str(args.measured_runs),
        "--fnb58-address",
        args.fnb58_address,
    ]
    if args.num_thread is not None:
        parts.extend(["--num-thread", str(args.num_thread)])
    if args.output_root != RUN_ROOT:
        parts.extend(["--output-root", str(args.output_root)])
    return " ".join(parts)


def _start_ssh_tunnel(args: argparse.Namespace, local_port: int) -> subprocess.Popen[str]:
    command = [
        "ssh",
        "-N",
        "-L",
        f"{local_port}:127.0.0.1:11434",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        f"{args.pi_user}@{args.pi_host}",
    ]
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _wait_for_ollama(base_url: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/api/version", timeout=2)
            if response.ok:
                return
        except requests.RequestException:
            time.sleep(0.5)
    raise RuntimeError(f"Ollama tunnel did not become reachable at {base_url}")


def _require_model(base_url: str, model: str) -> dict[str, Any]:
    response = requests.get(f"{base_url}/api/tags", timeout=10)
    response.raise_for_status()
    for item in response.json().get("models", []):
        if item.get("name") == model or item.get("model") == model:
            return dict(item)
    raise RuntimeError(f"Pi Ollama model {model!r} is not installed")


def _runtime_metadata(
    args: argparse.Namespace,
    pi_identity: dict[str, Any],
    model_info: dict[str, Any],
) -> RuntimeMetadata:
    details = model_info.get("details") or {}
    return RuntimeMetadata(
        runtime_name="ollama",
        runtime_version=pi_identity["ollama_version"],
        target_name="raspberry-pi-5-8gb",
        backend="pi5-cpu",
        model_name=str(model_info.get("name") or args.model),
        model_revision=str(model_info.get("digest") or "unknown"),
        quantization=details.get("quantization_level"),
        model_bytes=int(model_info["size"]) if model_info.get("size") else None,
        extra={
            "pi_host": args.pi_host,
            "pi_user": args.pi_user,
            "os_release": pi_identity["os_release"],
            "kernel": pi_identity["kernel"],
            "machine": pi_identity["machine"],
            "temp_c": pi_identity["temp_c"],
            "throttled": pi_identity["throttled"],
            "throttled_decoded": pi_identity["throttled_decoded"],
            "measurement_protocol": PROTOCOL_ID,
            "context_length": args.context_length,
            "num_thread": args.num_thread,
            "cooling_policy": PI5_CPU_COOLING_POLICY,
            "telemetry_basis": "real_physical_meters",
            "model_source": "ollama-local",
        },
    )


def _run_task_suite(
    args: argparse.Namespace,
    base_url: str,
    prompts: tuple[PromptCase, ...],
    *,
    phase: str,
    phase_index: int,
    is_warmup: bool,
    memory_monitor: RemoteMemoryMonitor,
) -> list[dict[str, Any]]:
    rows = []
    print(f"Starting {phase} session {phase_index} ({len(prompts)} tasks).", flush=True)
    for prompt in prompts:
        identity_start = _pi_identity(args)
        _abort_if_active_throttle(
            identity_start["throttled"], f"before {phase} {phase_index} {prompt.prompt_id}"
        )
        _abort_if_over_temp(
            identity_start, args.temp_limit_c, f"before {phase} {phase_index} {prompt.prompt_id}"
        )
        request = GenerationRequest(
            prompt_id=prompt.prompt_id, prompt=prompt.prompt, decode=prompt.decode
        )
        result = _generate(base_url, args.model, request, args=args)
        identity_end = _pi_identity(args)
        _abort_if_active_throttle(
            identity_end["throttled"], f"after {phase} {phase_index} {prompt.prompt_id}"
        )
        peak_memory_mb = memory_monitor.peak_between(result.started_at, result.finished_at)
        temp_max = max(identity_start["temp_c"] or 0.0, identity_end["temp_c"] or 0.0)
        exclusion_reasons: list[str] = []
        if is_warmup and temp_max > args.temp_limit_c:
            raise RuntimeError(
                f"Pi exceeded {args.temp_limit_c:g}C during warmup "
                f"{phase_index} {prompt.prompt_id}: {temp_max:.1f}C",
            )
        if not is_warmup and temp_max > args.temp_limit_c:
            exclusion_reasons.append(f"temperature_gt_{args.temp_limit_c:g}c")
        rows.append(
            {
                "phase": phase,
                "phase_index": phase_index,
                "is_warmup": is_warmup,
                "task_id": prompt.prompt_id,
                "task_type": prompt.task_type,
                "prompt": prompt.prompt,
                "decode": asdict(prompt.decode),
                "accuracy_expected": prompt.accuracy.expected,
                "started_at": result.started_at.isoformat(),
                "finished_at": result.finished_at.isoformat(),
                "duration_ms": result.duration_ms,
                "ttft_ms": result.first_token_ms,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "tokens_per_second": result.tokens_per_second,
                "output": result.text.strip(),
                "ollama": result.extra,
                "peak_memory_mb": peak_memory_mb,
                "temperature_start_c": identity_start["temp_c"],
                "temperature_end_c": identity_end["temp_c"],
                "throttle_start": identity_start["throttled"],
                "throttle_start_decoded": identity_start["throttled_decoded"],
                "throttle_end": identity_end["throttled"],
                "throttle_end_decoded": identity_end["throttled_decoded"],
                "excluded_from_stats": bool(exclusion_reasons),
                "exclusion_reasons": exclusion_reasons,
                "_result": result,
            },
        )
    return rows


def _generate(
    base_url: str,
    model: str,
    request: GenerationRequest,
    *,
    args: argparse.Namespace,
) -> GenerationResult:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": request.prompt,
        "stream": True,
        "options": {
            "num_predict": request.decode.max_tokens,
            "num_ctx": request.decode.num_ctx,
            "seed": request.decode.seed,
            "temperature": request.decode.temperature,
            "top_p": request.decode.top_p,
        },
    }
    if args.num_thread is not None:
        payload["options"]["num_thread"] = args.num_thread
    started_at = dt.datetime.now(dt.UTC)
    start_s = time.perf_counter()
    first_token_ms: float | None = None
    chunks: list[str] = []
    final: dict[str, Any] = {}
    response = requests.post(f"{base_url}/api/generate", json=payload, stream=True, timeout=1800)
    response.raise_for_status()
    next_thermal_poll = time.monotonic() + max(args.thermal_poll_s, 1.0)
    with response:
        for line in response.iter_lines(decode_unicode=True):
            if time.monotonic() >= next_thermal_poll:
                thermal = _pi_thermal_state(args)
                _abort_if_active_throttle(
                    thermal["throttled"],
                    f"during {request.prompt_id}",
                )
                _abort_if_over_temp(
                    thermal,
                    args.temp_limit_c,
                    f"during {request.prompt_id}",
                )
                next_thermal_poll = time.monotonic() + max(args.thermal_poll_s, 1.0)
            if not line:
                continue
            item = json.loads(line)
            token = str(item.get("response") or "")
            if token and first_token_ms is None:
                first_token_ms = (time.perf_counter() - start_s) * 1000.0
            chunks.append(token)
            if item.get("done"):
                final = item
    finished_at = dt.datetime.now(dt.UTC)
    duration_ms = (time.perf_counter() - start_s) * 1000.0
    text = "".join(chunks)
    return GenerationResult(
        prompt_id=request.prompt_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        first_token_ms=first_token_ms or duration_ms,
        tokens_in=int(final.get("prompt_eval_count") or max(1, len(request.prompt.split()))),
        tokens_out=int(final.get("eval_count") or max(1, len(text.split()))),
        text=text,
        peak_memory_mb=None,
        extra={
            "ollama_total_duration_ns": final.get("total_duration"),
            "ollama_load_duration_ns": final.get("load_duration"),
            "ollama_prompt_eval_count": final.get("prompt_eval_count"),
            "ollama_eval_count": final.get("eval_count"),
            "ollama_eval_duration_ns": final.get("eval_duration"),
        },
    )


def _attach_measurements(
    rows: list[dict[str, Any]],
    samples: tuple[TelemetrySample, ...],
    memory_samples: list[dict[str, float]],
) -> None:
    for row in rows:
        started_at = dt.datetime.fromisoformat(row["started_at"])
        finished_at = dt.datetime.fromisoformat(row["finished_at"])
        window_samples = _samples_between(samples, started_at, finished_at)
        power = power_series_by_source(window_samples, started_at=started_at)
        fnb = _energy_for_source(power.get("fnb58", ()), row["tokens_out"], started_at, finished_at)
        ina = _energy_for_source(
            power.get("ina219_0x40", ()), row["tokens_out"], started_at, finished_at
        )
        cross_check = compare_dual_meter(
            power,
            sources=("ina219_0x40", "fnb58"),
            threshold=0.10,
        )
        row["energy"] = {
            "fnb58_usb_delivery": fnb,
            "ina219_0x40_5v_system_rail": ina,
        }
        row["cross_check"] = asdict(cross_check)
        row["sample_counts"] = {source: len(series) for source, series in power.items()}
        row["peak_memory_mb"] = row["peak_memory_mb"] or _peak_memory_between(
            memory_samples,
            started_at,
            finished_at,
        )
        row.pop("_result", None)


def _energy_for_source(
    series: tuple[tuple[float, float], ...],
    tokens_out: int,
    started_at: dt.datetime,
    finished_at: dt.datetime,
) -> dict[str, float | int | None]:
    run_duration_s = max((finished_at - started_at).total_seconds(), 0.0)
    if len(series) < 2 or tokens_out <= 0:
        return {
            "sample_count": len(series),
            "total_j": None,
            "avg_power_w": None,
            "joules_per_token": None,
            "wh_per_1000_tokens": None,
            "telemetry_coverage": None,
        }
    total_j = integrate_joules(series)
    sample_duration_s = max(series[-1][0] - series[0][0], 0.0)
    joules_per_token = total_j / tokens_out
    return {
        "sample_count": len(series),
        "total_j": total_j,
        "avg_power_w": total_j / sample_duration_s if sample_duration_s > 0 else None,
        "joules_per_token": joules_per_token,
        "wh_per_1000_tokens": joules_per_token * 1000.0 / 3600.0,
        "telemetry_coverage": (
            min(sample_duration_s / run_duration_s, 1.0) if run_duration_s else None
        ),
    }


def _build_report(
    *,
    args: argparse.Namespace,
    run_id: str,
    runtime: RuntimeMetadata,
    workload: Any,
    command: str,
    environment: Any,
    pi_identity: dict[str, Any],
    invocation_rows: list[dict[str, Any]],
    measured_rows: list[dict[str, Any]],
    session_started_at: dt.datetime,
    session_finished_at: dt.datetime,
    samples: tuple[TelemetrySample, ...],
    accuracy: Any,
) -> dict[str, Any]:
    metric_summaries = _metric_summaries(measured_rows)
    by_task = {
        task.prompt_id: _metric_summaries(
            [row for row in measured_rows if row["task_id"] == task.prompt_id]
        )
        for task in workload.prompts
    }
    return {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "target": "raspberry-pi-5-8gb",
        "backend": "pi5-cpu",
        "measurement_protocol": PROTOCOL_ID,
        "supersedes": [
            "data/phase1/pi5-cpu/reference/phase1-pi5-cpu-20260611T043033Z/",
            "data/phase1/pi5-cpu/reference/phase1-pi5-cpu-publication-20260611T055902Z/",
        ],
        "canonical": True,
        "runtime": asdict(runtime),
        "workload": {
            "workload_id": workload.workload_id,
            "model": asdict(workload.model),
            "tasks": [
                {
                    "task_id": prompt.prompt_id,
                    "task_type": prompt.task_type,
                    "prompt": prompt.prompt,
                    "decode": asdict(prompt.decode),
                    "accuracy": asdict(prompt.accuracy),
                }
                for prompt in workload.prompts
            ],
        },
        "session": {
            "started_at": session_started_at.isoformat(),
            "finished_at": session_finished_at.isoformat(),
            "duration_s": (session_finished_at - session_started_at).total_seconds(),
            "warmup_sessions": args.warmups,
            "required_valid_measured_sessions": args.measured_runs,
            "valid_measured_sessions": _valid_measured_session_count(measured_rows),
            "temp_limit_c": args.temp_limit_c,
        },
        "telemetry": {
            "basis": "real_physical_meters",
            "energy_is_mock": False,
            "sources": {
                "fnb58": "USB cable delivery; headline Wh/1000 token source",
                "ina219_0x40": "Pi 5V system rail draw; context and cross-check source",
                "bme280_0x77": "ambient temperature, humidity, pressure",
            },
            "total_samples": _sample_counts(samples),
        },
        "accuracy": accuracy,
        "statistics": {
            "overall": metric_summaries,
            "by_task": by_task,
            "p99_over_p50_gate": _p99_gate(metric_summaries),
        },
        "invocations": invocation_rows,
        "environment": environment.to_dict(),
        "pi_identity_start": pi_identity,
        "reproducibility": {
            "command": command,
            "git_commit": environment.git_sha,
            "git_dirty": environment.git_dirty,
        },
    }


def _metric_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    metrics = {
        "tokens_per_second": [row["tokens_per_second"] for row in rows],
        "ttft_ms": [row["ttft_ms"] for row in rows],
        "fnb58_wh_per_1000_tokens": [
            row["energy"]["fnb58_usb_delivery"]["wh_per_1000_tokens"] for row in rows
        ],
        "fnb58_joules_per_token": [
            row["energy"]["fnb58_usb_delivery"]["joules_per_token"] for row in rows
        ],
        "ina219_joules_per_token": [
            row["energy"]["ina219_0x40_5v_system_rail"]["joules_per_token"] for row in rows
        ],
        "cross_check_relative_delta": [row["cross_check"]["relative_delta"] for row in rows],
        "temperature_start_c": [row["temperature_start_c"] for row in rows],
        "temperature_end_c": [row["temperature_end_c"] for row in rows],
    }
    return {name: _summarize(values) for name, values in metrics.items()}


def _summarize(values: list[Any]) -> dict[str, float | int | None]:
    clean = sorted(
        float(value) for value in values if value is not None and math.isfinite(float(value))
    )
    if not clean:
        return {
            "count": 0,
            "p50": None,
            "p95": None,
            "p99": None,
            "stddev": None,
            "mean": None,
            "min": None,
            "max": None,
            "p99_over_p50": None,
        }
    p50 = _percentile(clean, 0.50)
    p95 = _percentile(clean, 0.95)
    p99 = _percentile(clean, 0.99)
    return {
        "count": len(clean),
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "stddev": statistics.stdev(clean) if len(clean) > 1 else 0.0,
        "mean": statistics.fmean(clean),
        "min": clean[0],
        "max": clean[-1],
        "p99_over_p50": p99 / p50 if p50 else None,
    }


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _p99_gate(summaries: dict[str, dict[str, float | int | None]]) -> dict[str, Any]:
    per_metric = {
        name: summary["p99_over_p50"] < 1.4 if summary["p99_over_p50"] is not None else False
        for name, summary in summaries.items()
        if name not in {"temperature_start_c", "temperature_end_c", "cross_check_relative_delta"}
    }
    if "cross_check_relative_delta" in summaries:
        value = summaries["cross_check_relative_delta"]["p99_over_p50"]
        per_metric["cross_check_relative_delta"] = value < 1.4 if value is not None else False
    return {"threshold": 1.4, "per_metric": per_metric, "passed": all(per_metric.values())}


def _render_markdown(report: dict[str, Any]) -> str:
    stats = report["statistics"]["overall"]
    lines = [
        "# Phase 1 Pi 5 CPU Canonical Report",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Protocol: `{report['measurement_protocol']}`",
        f"- Target/backend: `{report['target']}` / `{report['backend']}`",
        f"- Runtime: `{report['runtime']['runtime_name']}` `{report['runtime']['runtime_version']}`",
        f"- Ollama num_thread: `{report['runtime']['extra'].get('num_thread')}`",
        f"- Cooling policy: {report['runtime']['extra'].get('cooling_policy')}",
        f"- Model: `{report['runtime']['model_name']}`",
        f"- Model digest: `{report['runtime']['model_revision']}`",
        f"- Quantization: `{report['runtime']['quantization']}`",
        f"- Warmup sessions: `{report['session']['warmup_sessions']}`",
        f"- Valid measured sessions: `{report['session']['valid_measured_sessions']}`",
        f"- Headline FNB58 Wh/1000 tokens p50: `{_fmt(stats['fnb58_wh_per_1000_tokens']['p50'])}`",
        f"- Accuracy: `{report['accuracy']['score']:.3f}` "
        f"({report['accuracy']['passed']}/{report['accuracy']['total']})",
        f"- p99/p50 gate: `{report['statistics']['p99_over_p50_gate']['passed']}`",
        "",
        "## Overall Statistics",
        "",
        "| Metric | Count | P50 | P95 | P99 | Stddev |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for metric, summary in stats.items():
        lines.append(
            f"| `{metric}` | {summary['count']} | {_fmt(summary['p50'])} | "
            f"{_fmt(summary['p95'])} | {_fmt(summary['p99'])} | {_fmt(summary['stddev'])} |",
        )
    lines.extend(["", "## Task Statistics", ""])
    for task_id, task_stats in report["statistics"]["by_task"].items():
        lines.extend(
            [
                f"### `{task_id}`",
                "",
                "| Metric | Count | P50 | P95 | P99 | Stddev |",
                "|---|---:|---:|---:|---:|---:|",
            ],
        )
        for metric, summary in task_stats.items():
            lines.append(
                f"| `{metric}` | {summary['count']} | {_fmt(summary['p50'])} | "
                f"{_fmt(summary['p95'])} | {_fmt(summary['p99'])} | {_fmt(summary['stddev'])} |",
            )
        lines.append("")
    lines.extend(
        [
            "## Invocation Summary",
            "",
            "| Phase | Session | Task | Included | Temp C start/end | Throttle start | tok/s | TTFT ms | FNB58 Wh/1k | INA219 J/tok | Delta |",
            "|---|---:|---|---|---:|---|---:|---:|---:|---:|---:|",
        ],
    )
    for row in report["invocations"]:
        lines.append(
            f"| {row['phase']} | {row['phase_index']} | `{row['task_id']}` | "
            f"`{not row['excluded_from_stats'] and not row['is_warmup']}` | "
            f"{_fmt(row['temperature_start_c'])}/{_fmt(row['temperature_end_c'])} | "
            f"`{row['throttle_start']['raw']}` | {_fmt(row['tokens_per_second'])} | "
            f"{_fmt(row['ttft_ms'])} | "
            f"{_fmt(row['energy']['fnb58_usb_delivery']['wh_per_1000_tokens'])} | "
            f"{_fmt(row['energy']['ina219_0x40_5v_system_rail']['joules_per_token'])} | "
            f"{_fmt(row['cross_check']['relative_delta'])} |",
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            "```bash",
            report["reproducibility"]["command"],
            "```",
        ],
    )
    return "\n".join(lines).rstrip() + "\n"


def _classification_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classification_rows = [row for row in rows if row["task_type"] == "classification"]
    scores = []
    for row in classification_rows:
        expected = [str(item).lower() for item in row["accuracy_expected"]]
        observed = str(row["output"]).lower()
        passed = all(item in observed for item in expected)
        scores.append(
            {
                "phase_index": row["phase_index"],
                "task_id": row["task_id"],
                "passed": passed,
                "expected": row["accuracy_expected"],
                "observed": row["output"],
            },
        )
    passed_count = sum(1 for score in scores if score["passed"])
    total = len(scores)
    return {
        "metric": "classification_contains_all",
        "passed": passed_count,
        "total": total,
        "score": passed_count / total if total else 0.0,
        "prompt_scores": scores,
    }


def _is_stats_row(row: dict[str, Any]) -> bool:
    return not row["is_warmup"] and not row["excluded_from_stats"]


def _valid_measured_session_count(rows: list[dict[str, Any]]) -> int:
    sessions: dict[int, set[str]] = {}
    for row in rows:
        sessions.setdefault(row["phase_index"], set()).add(row["task_id"])
    return sum(1 for tasks in sessions.values() if len(tasks) == 3)


def _samples_between(
    samples: tuple[TelemetrySample, ...],
    started_at: dt.datetime,
    finished_at: dt.datetime,
) -> tuple[TelemetrySample, ...]:
    selected = []
    for sample in samples:
        timestamp = (
            sample.timestamp if sample.timestamp.tzinfo else sample.timestamp.replace(tzinfo=dt.UTC)
        )
        timestamp = timestamp.astimezone(dt.UTC)
        if started_at <= timestamp <= finished_at:
            selected.append(sample)
    return tuple(selected)


def _sample_counts(samples: tuple[TelemetrySample, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        counts[sample.source_name] = counts.get(sample.source_name, 0) + 1
    return counts


def _peak_memory_between(
    samples: list[dict[str, float]],
    started_at: dt.datetime,
    finished_at: dt.datetime,
) -> float | None:
    start_ts = started_at.timestamp()
    finish_ts = finished_at.timestamp()
    values = [
        sample["rss_mb"] for sample in samples if start_ts <= sample["timestamp_unix"] <= finish_ts
    ]
    return max(values) if values else None


def _pi_identity(args: argparse.Namespace) -> dict[str, Any]:
    script = (
        "set -e; "
        "echo OS_RELEASE=$(tr '\\n' ';' </etc/os-release); "
        "echo KERNEL=$(uname -r); "
        "echo MACHINE=$(uname -m); "
        "echo OLLAMA_VERSION=$(ollama --version); "
        "echo THROTTLED=$(vcgencmd get_throttled 2>/dev/null || true); "
        "echo TEMP=$(vcgencmd measure_temp 2>/dev/null || true)"
    )
    output = _ssh_text(args, script)
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    throttle = values.get("THROTTLED", "unknown")
    return {
        "os_release": values.get("OS_RELEASE", "unknown"),
        "kernel": values.get("KERNEL", "unknown"),
        "machine": values.get("MACHINE", "unknown"),
        "ollama_version": values.get("OLLAMA_VERSION", "unknown"),
        "throttled": {"raw": throttle, "decoded": _decode_throttled(throttle)},
        "throttled_decoded": _decode_throttled(throttle),
        "temp_raw": values.get("TEMP", "unknown"),
        "temp_c": _parse_temp_c(values.get("TEMP", "")),
    }


def _capture_pi_clock_state(args: argparse.Namespace) -> dict[str, Any]:
    state: dict[str, Any] = {
        "captured_at": dt.datetime.now(dt.UTC).isoformat(),
        "source": "vcgencmd measure_clock",
        "warnings": [],
    }
    warnings: list[str] = state["warnings"]
    script = (
        "echo ARM=$(vcgencmd measure_clock arm 2>&1 || true); "
        "echo CORE=$(vcgencmd measure_clock core 2>&1 || true)"
    )
    try:
        output = _ssh_text(args, script, timeout=10)
    except Exception as exc:
        warning = f"Pi 5 clock capture failed: {exc}"
        warnings.append(warning)
        print(f"Warning: {warning}", file=sys.stderr, flush=True)
        state.update({"status": "unavailable", "raw": "", "error": str(exc)})
        return state

    values: dict[str, str] = {}
    for line in output.splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    arm_raw = values.get("ARM", "unknown")
    core_raw = values.get("CORE", "unknown")
    state.update(
        {
            "raw": output,
            "arm": {"raw": arm_raw, "hz": _parse_vcgencmd_clock_hz(arm_raw)},
            "core": {"raw": core_raw, "hz": _parse_vcgencmd_clock_hz(core_raw)},
        },
    )
    if state["arm"]["hz"] is not None and state["core"]["hz"] is not None:
        state["status"] = "ok"
    elif state["arm"]["hz"] is not None or state["core"]["hz"] is not None:
        state["status"] = "partial"
        warning = "Pi 5 clock capture only recorded one of arm/core clock state."
        warnings.append(warning)
        print(f"Warning: {warning}", file=sys.stderr, flush=True)
    else:
        state["status"] = "unavailable"
        warning = "Pi 5 clock capture did not record arm or core clock state."
        warnings.append(warning)
        print(f"Warning: {warning}", file=sys.stderr, flush=True)
    return state


def _parse_vcgencmd_clock_hz(raw: str) -> int | None:
    _, separator, value = raw.rpartition("=")
    if not separator:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _pi_thermal_state(args: argparse.Namespace) -> dict[str, Any]:
    script = (
        "echo THROTTLED=$(vcgencmd get_throttled 2>/dev/null || true); "
        "echo TEMP=$(vcgencmd measure_temp 2>/dev/null || true)"
    )
    output = _ssh_text(args, script, timeout=10)
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    throttle = values.get("THROTTLED", "unknown")
    return {
        "throttled": {"raw": throttle, "decoded": _decode_throttled(throttle)},
        "throttled_decoded": _decode_throttled(throttle),
        "temp_raw": values.get("TEMP", "unknown"),
        "temp_c": _parse_temp_c(values.get("TEMP", "")),
    }


def _abort_if_active_throttle(throttle: dict[str, Any], label: str) -> None:
    decoded = throttle["decoded"]
    active = (
        decoded.get("active_under_voltage")
        or decoded.get("active_freq_capped")
        or decoded.get("active_throttled")
        or decoded.get("active_soft_temp_limit")
    )
    print(f"Pi throttle register {label}: {throttle['raw']}", flush=True)
    if active:
        raise RuntimeError(f"Pi is actively throttled {label}: {throttle['raw']}")


def _abort_if_over_temp(identity: dict[str, Any], temp_limit_c: float, label: str) -> None:
    temp_c = identity.get("temp_c")
    if temp_c is None:
        return
    if temp_c > temp_limit_c:
        raise RuntimeError(f"Pi temperature {label} exceeds {temp_limit_c:g}C: {temp_c:.1f}C")


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


def _parse_temp_c(value: str) -> float | None:
    try:
        return float(value.split("=", 1)[1].split("'", 1)[0])
    except (IndexError, ValueError):
        return None


def _ssh_text(args: argparse.Namespace, remote_command: str, *, timeout: int = 30) -> str:
    completed = subprocess.run(
        [
            "ssh",
            f"{args.pi_user}@{args.pi_host}",
            remote_command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def _live_sources(args: argparse.Namespace) -> tuple[Any, ...]:
    return (
        FnirsiSource(FnirsiSourceConfig(address=args.fnb58_address, name="fnb58")),
        Ina219Source(Ina219Config(name="ina219_0x40", address=0x40, sample_rate_hz=8.0)),
        Bme280Source(Bme280Config(name="bme280_0x77", address=0x77, sample_rate_hz=1.0)),
    )


def _set_default_blinka_env() -> None:
    os.environ.setdefault("BLINKA_MCP2221", "1")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_latest_pointer(pointer: Path, target: Path) -> None:
    pointer.parent.mkdir(parents=True, exist_ok=True)
    target_path = target if target.is_absolute() else ROOT / target
    pointer.write_text(
        json.dumps({"latest": str(target_path.resolve().relative_to(ROOT.resolve()))}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)


if __name__ == "__main__":
    main()
