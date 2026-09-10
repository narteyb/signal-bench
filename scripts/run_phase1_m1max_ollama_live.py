#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the canonical Phase 1 M1 Max Ollama benchmark with live FNB58 telemetry."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import re
import shlex
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
    integrate_joules,
    power_series_by_source,
)
from signal_bench.phase1.runtime import GenerationRequest, GenerationResult, RuntimeMetadata
from signal_bench.phase1.workload import PromptCase, canonical_llm_workload
from signal_bench.telemetry import FnirsiSource, FnirsiSourceConfig, TelemetrySample

DEFAULT_FNB58_ADDRESS = "<fnb58-address>"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_WARMUPS = 5
DEFAULT_MEASURED = 20
DEFAULT_MAX_MEASURED_ATTEMPTS = 30
DEFAULT_THERMAL_PRESSURE_LIMIT = 2
DEFAULT_CONTEXT_LENGTH = 4096
PROTOCOL_ID = "n20_plus_5_v1"
RUN_ROOT = ROOT / "data" / "phase1" / "m1max" / "canonical"
SWEEP_ROOT = ROOT / "data" / "phase1" / "m1max" / "gpu-layer-sweep"

THERMAL_PRESSURE_LEVELS = {"nominal": 0, "moderate": 1, "heavy": 2, "trapping": 3}
THERMAL_PRESSURE_RE = re.compile(r"(?im)^\s*Current pressure level:\s*([A-Za-z]+)\s*$")
POWER_RE = re.compile(
    r"(?im)^\s*(CPU|GPU|ANE|Combined|Package)\s+Power\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*(m?W)\b",
)
OPTIMIZED_CHARGING_ABORT = """PREFLIGHT FAILED: Optimized Battery Charging is suppressing the charge.
The FNB58 will underread actual system energy consumption.

To fix:
  1. Open System Settings > Battery > Battery Health.
  2. Disable Optimized Battery Charging.
  3. Wait for the battery to reach 95% or higher.
  4. Re-run the benchmark.

Alternatively, charge to 100% with Optimized Charging enabled, then run."""


def main() -> None:
    args = _parse_args()
    environment = collect_environment(ROOT)
    command = _repro_command(args)
    preflight = _preflight(args)
    model_info = _require_model(args.ollama_url, args.model)
    workload = canonical_llm_workload(args.model)
    thermal_reader = PowermetricsReader(args.powermetrics_samplers, args.powermetrics_interval_ms)
    try:
        thermal_reader.start()
        sweep = _run_gpu_sweep(args, workload, thermal_reader)
        selected_num_gpu = sweep["selected"]["num_gpu"]
        run_id = f"phase1-m1max-canonical-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
        run_root = args.output_root
        output_dir = run_root / run_id
        runtime = _runtime_metadata(args, model_info, preflight, selected_num_gpu)

        sources = (FnirsiSource(FnirsiSourceConfig(address=args.fnb58_address, name="fnb58")),)
        recorder = TelemetryRecorder(sources)
        recorder_session = AsyncRecorderSession(recorder)
        memory_monitor = LocalMemoryMonitor()
        session_started_at = dt.datetime.now(dt.UTC)
        recorder_session.start()
        memory_monitor.start()
        invocation_rows: list[dict[str, Any]] = []
        try:
            for warmup_index in range(1, args.warmups + 1):
                invocation_rows.extend(
                    _run_task_suite(
                        args,
                        workload.prompts,
                        thermal_reader,
                        phase="warmup",
                        phase_index=warmup_index,
                        is_warmup=True,
                        num_gpu=selected_num_gpu,
                        memory_monitor=memory_monitor,
                    ),
                )

            valid_measured_sessions = 0
            measured_attempt = 0
            while valid_measured_sessions < args.measured_runs:
                measured_attempt += 1
                if measured_attempt > args.max_measured_attempts:
                    raise RuntimeError(
                        f"Unable to collect {args.measured_runs} valid measured sessions "
                        f"within {args.max_measured_attempts} attempts.",
                    )
                rows = _run_task_suite(
                    args,
                    workload.prompts,
                    thermal_reader,
                    phase="measured",
                    phase_index=measured_attempt,
                    is_warmup=False,
                    num_gpu=selected_num_gpu,
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
                        {reason for row in rows for reason in row["exclusion_reasons"]}
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
            preflight=preflight,
            sweep=sweep,
            environment=environment,
            invocation_rows=invocation_rows,
            measured_rows=measured_rows,
            session_started_at=session_started_at,
            session_finished_at=session_finished_at,
            samples=samples,
            accuracy=accuracy,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "phase1-m1max-canonical-report.json"
        md_path = output_dir / "phase1-m1max-canonical-report.md"
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(_render_markdown(report), encoding="utf-8")
        _write_latest_pointer(run_root / "latest.json", json_path)
        print(f"Canonical JSON: {json_path}")
        print(f"Canonical Markdown: {md_path}")
    finally:
        thermal_reader.stop()


class AsyncRecorderSession:
    """Run a telemetry recorder on a persistent asyncio event loop."""

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


class LocalMemoryMonitor:
    """Poll aggregate local Ollama RSS while the benchmark runs."""

    def __init__(self) -> None:
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
        return _peak_memory_between(self.samples, started_at, finished_at)

    def _run(self) -> None:
        while not self._stop.is_set():
            completed = subprocess.run(
                [
                    "ps",
                    "-axo",
                    "rss=,comm=",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            rss_kb = 0.0
            if completed.returncode == 0:
                for line in completed.stdout.splitlines():
                    parts = line.split(None, 1)
                    if len(parts) != 2:
                        continue
                    command = parts[1]
                    if command.endswith("/ollama") or "ollama" in command or "llama" in command:
                        try:
                            rss_kb += float(parts[0])
                        except ValueError:
                            continue
            self.samples.append({"timestamp_unix": time.time(), "rss_mb": rss_kb / 1024.0})
            self._stop.wait(1.0)


class PowermetricsReader:
    """Read one macOS thermal/power snapshot from powermetrics."""

    def __init__(self, samplers: str, interval_ms: int) -> None:
        self._samplers = samplers
        self._interval_ms = interval_ms

    def start(self) -> None:
        try:
            self.read()
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc

    def stop(self) -> None:
        return

    def read(self) -> dict[str, Any]:
        command = self._command()
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(10, self._interval_ms // 1000 + 10),
        )
        if completed.returncode != 0:
            completed = self._read_with_macos_admin_prompt()
        parsed = parse_powermetrics_snapshot(completed.stdout)
        parsed["raw"] = completed.stdout
        parsed["captured_at"] = dt.datetime.now(dt.UTC).isoformat()
        if parsed.get("thermal_pressure_level") is None:
            raise RuntimeError(
                "powermetrics output did not include thermal pressure. The M1 Max "
                "canonical run requires `powermetrics --samplers thermal` pressure "
                "at the start and end of every run."
            )
        return parsed

    def _command(self) -> list[str]:
        return [
            "sudo",
            "-n",
            "powermetrics",
            "--samplers",
            self._samplers,
            "-n",
            "1",
            "-i",
            str(self._interval_ms),
        ]

    def _read_with_macos_admin_prompt(self) -> subprocess.CompletedProcess[str]:
        shell = (
            f"/usr/bin/powermetrics --samplers {shlex.quote(self._samplers)} "
            f"-n 1 -i {int(self._interval_ms)}"
        )
        applescript = f"do shell script {json.dumps(shell)} with administrator privileges"
        completed = subprocess.run(
            ["osascript", "-e", applescript],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(30, self._interval_ms // 1000 + 30),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                "powermetrics thermal-pressure capture requires administrator "
                "privilege. Non-interactive sudo failed and the macOS admin prompt "
                "did not return a sample." + (f" powermetrics output: {detail}" if detail else "")
            )
        return completed


def parse_powermetrics_snapshot(text: str) -> dict[str, Any]:
    """Parse one powermetrics sample into the fields required by Phase 1."""
    pressure_name = None
    pressure_level = None
    pressure_match = THERMAL_PRESSURE_RE.search(text)
    if pressure_match is not None:
        pressure_name = pressure_match.group(1).strip().lower()
        pressure_level = THERMAL_PRESSURE_LEVELS.get(pressure_name)
    powers: dict[str, float] = {}
    for label, value, unit in POWER_RE.findall(text):
        watts = float(value) / 1000.0 if unit.lower() == "mw" else float(value)
        powers[f"{label.lower()}_power_w"] = watts
    return {
        "thermal_pressure_name": pressure_name,
        "thermal_pressure_level": pressure_level,
        "power_estimates_w": powers,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--fnb58-address", default=DEFAULT_FNB58_ADDRESS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--measured-runs", type=int, default=DEFAULT_MEASURED)
    parser.add_argument("--max-measured-attempts", type=int, default=DEFAULT_MAX_MEASURED_ATTEMPTS)
    parser.add_argument(
        "--thermal-pressure-limit", type=int, default=DEFAULT_THERMAL_PRESSURE_LIMIT
    )
    parser.add_argument("--context-length", type=int, default=DEFAULT_CONTEXT_LENGTH)
    parser.add_argument("--gpu-sweep", default="0,16,32,default")
    parser.add_argument("--powermetrics-samplers", default="thermal,cpu_power,gpu_power")
    parser.add_argument("--powermetrics-interval-ms", type=int, default=1000)
    parser.add_argument("--output-root", type=Path, default=RUN_ROOT)
    return parser.parse_args()


def _repro_command(args: argparse.Namespace) -> str:
    command = (
        "uv run python scripts/run_phase1_m1max_ollama_live.py "
        f"--model {args.model} --warmups {args.warmups} "
        f"--measured-runs {args.measured_runs} --fnb58-address {args.fnb58_address} "
        f"--gpu-sweep {args.gpu_sweep}"
    )
    if args.output_root != RUN_ROOT:
        command += f" --output-root {args.output_root}"
    return command


def _preflight(args: argparse.Namespace) -> dict[str, Any]:
    pmset = _run_text(["pmset", "-g"])
    batt = _run_text(["pmset", "-g", "batt"])
    if "Now drawing from 'AC Power'" not in batt:
        raise SystemExit("M1 Max benchmark preflight failed: AC power is not active.")
    powermode_values = [
        int(value) for value in re.findall(r"(?m)^\s*powermode\s+([0-9]+)\s*$", pmset)
    ]
    low_power_mode_off = not powermode_values or all(value == 0 for value in powermode_values)
    if not low_power_mode_off:
        raise SystemExit(
            f"M1 Max benchmark preflight failed: Low Power Mode appears enabled: {powermode_values}"
        )
    battery = _parse_battery_state(batt)
    if not (battery["fully_charged"] or battery["actively_charging"]):
        raise SystemExit(OPTIMIZED_CHARGING_ABORT)
    return {
        "pmset_g": pmset,
        "pmset_batt": batt,
        "ac_power": True,
        "low_power_mode_off": True,
        "powermode_values": powermode_values,
        "battery_percent": battery["percent"],
        "battery_state": battery["state"],
        "battery_fully_charged": battery["fully_charged"],
        "battery_actively_charging": battery["actively_charging"],
        "optimized_battery_charging_gate_passed": True,
        "ollama_version": _ollama_version(),
        "os_version": _run_text(["sw_vers"]).strip(),
        "kernel": _run_text(["uname", "-r"]).strip(),
        "machine": _run_text(["uname", "-m"]).strip(),
    }


def _parse_battery_state(pmset_batt: str) -> dict[str, Any]:
    battery_line = next(
        (line.strip() for line in pmset_batt.splitlines() if "InternalBattery" in line),
        "",
    )
    percent_match = re.search(r"\b([0-9]{1,3})%;", battery_line)
    if not percent_match:
        raise SystemExit(
            f"M1 Max benchmark preflight failed: could not parse battery state from pmset: {pmset_batt!r}"
        )
    percent = int(percent_match.group(1))
    fields = [field.strip().lower() for field in battery_line.split(";")]
    state = "; ".join(fields[1:])
    actively_charging = "charging" in state and "not charging" not in state
    fully_charged = percent >= 100
    return {
        "percent": percent,
        "state": state,
        "actively_charging": actively_charging,
        "fully_charged": fully_charged,
    }


def _ollama_version() -> str:
    return _run_text(["ollama", "--version"]).strip()


def _require_model(base_url: str, model: str) -> dict[str, Any]:
    _wait_for_ollama(base_url)
    response = requests.get(f"{base_url}/api/tags", timeout=10)
    response.raise_for_status()
    for item in response.json().get("models", []):
        if item.get("name") == model or item.get("model") == model:
            return dict(item)
    raise RuntimeError(f"Local Ollama model {model!r} is not installed")


def _wait_for_ollama(base_url: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/api/version", timeout=2)
            if response.ok:
                return
        except requests.RequestException:
            time.sleep(0.5)
    raise RuntimeError(f"Ollama is not reachable at {base_url}")


def _runtime_metadata(
    args: argparse.Namespace,
    model_info: dict[str, Any],
    preflight: dict[str, Any],
    num_gpu: int | None,
) -> RuntimeMetadata:
    details = model_info.get("details") or {}
    return RuntimeMetadata(
        runtime_name="ollama",
        runtime_version=preflight["ollama_version"],
        target_name="m1-max-macbook-pro-64gb",
        backend="m1max-ollama-metal",
        model_name=str(model_info.get("name") or args.model),
        model_revision=str(model_info.get("digest") or "unknown"),
        quantization=details.get("quantization_level"),
        model_bytes=int(model_info["size"]) if model_info.get("size") else None,
        extra={
            "os_version": preflight["os_version"],
            "kernel": preflight["kernel"],
            "machine": preflight["machine"],
            "measurement_protocol": PROTOCOL_ID,
            "context_length": args.context_length,
            "num_gpu": "default" if num_gpu is None else num_gpu,
            "telemetry_basis": "partial_real_physical_meter_fnb58_only",
            "model_source": "ollama-local",
            "thermal_source": "powermetrics --samplers thermal",
            "powermetrics_samplers": args.powermetrics_samplers,
            "thermal_pressure_abort_level": args.thermal_pressure_limit,
            "cooling_policy": (
                "MacBook Pro built-in thermal system; AC power required; Low Power Mode off; "
                "battery must be 100% or actively charging."
            ),
        },
    )


def _run_gpu_sweep(
    args: argparse.Namespace,
    workload: Any,
    thermal_reader: PowermetricsReader,
) -> dict[str, Any]:
    run_id = f"m1max-gpu-layer-sweep-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    output_dir = SWEEP_ROOT / run_id
    candidates = _gpu_candidates(args.gpu_sweep)
    throughput_prompt = next(
        prompt for prompt in workload.prompts if prompt.prompt_id == "throughput-512"
    )
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        label = "default" if candidate is None else str(candidate)
        print(f"GPU sweep candidate num_gpu={label}", flush=True)
        start = thermal_reader.read()
        result = _generate(
            args.ollama_url, args.model, throughput_prompt, args=args, num_gpu=candidate
        )
        end = thermal_reader.read()
        results.append(
            {
                "num_gpu": candidate,
                "label": label,
                "tokens_per_second": result.tokens_per_second,
                "ttft_ms": result.first_token_ms,
                "tokens_out": result.tokens_out,
                "duration_ms": result.duration_ms,
                "thermal_pressure_start": start["thermal_pressure_level"],
                "thermal_pressure_start_name": start["thermal_pressure_name"],
                "thermal_pressure_end": end["thermal_pressure_level"],
                "thermal_pressure_end_name": end["thermal_pressure_name"],
                "thermal_pressure_flag": end["thermal_pressure_level"]
                >= args.thermal_pressure_limit,
                "powermetrics_power_estimates_end_w": end["power_estimates_w"],
            },
        )
    valid = [row for row in results if not row["thermal_pressure_flag"]]
    if not valid:
        raise RuntimeError("All GPU sweep candidates reached heavy-or-worse thermal pressure.")
    selected = max(valid, key=lambda row: row["tokens_per_second"])
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "target": "m1-max-macbook-pro-64gb",
        "model": args.model,
        "task": "throughput-512",
        "thermal_pressure_abort_level": args.thermal_pressure_limit,
        "candidates": results,
        "selected": selected,
        "note": (
            "Sweep uses the 512-token throughput task only. powermetrics power values "
            "are supplementary estimates, not measurement-grade energy."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "gpu-layer-sweep-report.json"
    md_path = output_dir / "gpu-layer-sweep-report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_sweep_markdown(report), encoding="utf-8")
    _write_latest_pointer(SWEEP_ROOT / "latest.json", json_path)
    print(f"GPU sweep JSON: {json_path}")
    print(f"GPU sweep Markdown: {md_path}")
    return report


def _gpu_candidates(text: str) -> list[int | None]:
    values: list[int | None] = []
    for item in text.split(","):
        item = item.strip().lower()
        if item in {"", "none"}:
            continue
        candidate = None if item == "default" else int(item)
        if candidate not in values:
            values.append(candidate)
    if 0 not in values:
        values.insert(0, 0)
    if None not in values:
        values.append(None)
    return values


def _run_task_suite(
    args: argparse.Namespace,
    prompts: tuple[PromptCase, ...],
    thermal_reader: PowermetricsReader,
    *,
    phase: str,
    phase_index: int,
    is_warmup: bool,
    num_gpu: int | None,
    memory_monitor: LocalMemoryMonitor,
) -> list[dict[str, Any]]:
    rows = []
    print(f"Starting {phase} session {phase_index} ({len(prompts)} tasks).", flush=True)
    for prompt in prompts:
        thermal_start = thermal_reader.read()
        _abort_if_thermal_pressure(
            thermal_start,
            args.thermal_pressure_limit,
            f"before {phase} {phase_index} {prompt.prompt_id}",
        )
        result = _generate(args.ollama_url, args.model, prompt, args=args, num_gpu=num_gpu)
        thermal_end = thermal_reader.read()
        peak_memory_mb = memory_monitor.peak_between(result.started_at, result.finished_at)
        exclusion_reasons: list[str] = []
        end_pressure = int(thermal_end["thermal_pressure_level"])
        if is_warmup and end_pressure >= args.thermal_pressure_limit:
            raise RuntimeError(
                "M1 Max reached heavy-or-worse thermal pressure during warmup "
                f"{phase_index} {prompt.prompt_id}: "
                f"{end_pressure} ({thermal_end['thermal_pressure_name']})",
            )
        if not is_warmup and end_pressure >= args.thermal_pressure_limit:
            exclusion_reasons.append(f"thermal_pressure_ge_{args.thermal_pressure_limit}")
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
                "thermal_start": _compact_thermal(thermal_start),
                "thermal_end": _compact_thermal(thermal_end),
                "thermal_pressure_start": thermal_start["thermal_pressure_level"],
                "thermal_pressure_start_name": thermal_start["thermal_pressure_name"],
                "thermal_pressure_end": thermal_end["thermal_pressure_level"],
                "thermal_pressure_end_name": thermal_end["thermal_pressure_name"],
                "powermetrics_power_estimates_start_w": thermal_start["power_estimates_w"],
                "powermetrics_power_estimates_end_w": thermal_end["power_estimates_w"],
                "excluded_from_stats": bool(exclusion_reasons),
                "exclusion_reasons": exclusion_reasons,
                "_result": result,
            },
        )
    return rows


def _generate(
    base_url: str,
    model: str,
    prompt: PromptCase,
    *,
    args: argparse.Namespace,
    num_gpu: int | None,
) -> GenerationResult:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt.prompt,
        "stream": True,
        "options": {
            "num_predict": prompt.decode.max_tokens,
            "num_ctx": prompt.decode.num_ctx,
            "seed": prompt.decode.seed,
            "temperature": prompt.decode.temperature,
            "top_p": prompt.decode.top_p,
        },
    }
    if num_gpu is not None:
        payload["options"]["num_gpu"] = num_gpu
    request = GenerationRequest(
        prompt_id=prompt.prompt_id, prompt=prompt.prompt, decode=prompt.decode
    )
    started_at = dt.datetime.now(dt.UTC)
    start_s = time.perf_counter()
    first_token_ms: float | None = None
    chunks: list[str] = []
    final: dict[str, Any] = {}
    response = requests.post(f"{base_url}/api/generate", json=payload, stream=True, timeout=1800)
    response.raise_for_status()
    with response:
        for line in response.iter_lines(decode_unicode=True):
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
            "num_gpu": "default" if num_gpu is None else num_gpu,
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
        row["energy"] = {"fnb58_usb_c_charger_delivery": fnb}
        row["telemetry_status"] = {
            "label": "partial-telemetry",
            "reason": "M1 Max is sealed; no rail-side INA219 path is available.",
            "cross_check": "not_applicable_no_rail_meter",
        }
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
    preflight: dict[str, Any],
    sweep: dict[str, Any],
    environment: Any,
    invocation_rows: list[dict[str, Any]],
    measured_rows: list[dict[str, Any]],
    session_started_at: dt.datetime,
    session_finished_at: dt.datetime,
    samples: tuple[TelemetrySample, ...],
    accuracy: dict[str, Any],
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
        "target": "m1-max-macbook-pro-64gb",
        "backend": "m1max-ollama-metal",
        "measurement_protocol": PROTOCOL_ID,
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
            "thermal_pressure_abort_level": args.thermal_pressure_limit,
            "excluded_for_thermal_pressure": sum(
                1
                for row in invocation_rows
                if f"thermal_pressure_ge_{args.thermal_pressure_limit}" in row["exclusion_reasons"]
            ),
        },
        "telemetry": {
            "label": "partial-telemetry",
            "basis": "real_physical_meter_fnb58_only",
            "energy_is_mock": False,
            "sources": {
                "fnb58": "USB-C charger delivery; authoritative headline Wh/1000 token source",
            },
            "unavailable_sources": {
                "ina219": "M1 Max is a sealed laptop; no rail-side measurement point is available.",
            },
            "cross_check": "not_applicable_no_rail_meter",
            "total_samples": _sample_counts(samples),
        },
        "gpu_layer_sweep": sweep,
        "accuracy": accuracy,
        "statistics": {
            "overall": metric_summaries,
            "by_task": by_task,
            "p99_over_p50_gate": _p99_gate(metric_summaries),
            "thermal_drift": _thermal_drift(measured_rows),
        },
        "invocations": invocation_rows,
        "preflight": preflight,
        "environment": environment.to_dict(),
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
            row["energy"]["fnb58_usb_c_charger_delivery"]["wh_per_1000_tokens"] for row in rows
        ],
        "fnb58_joules_per_token": [
            row["energy"]["fnb58_usb_c_charger_delivery"]["joules_per_token"] for row in rows
        ],
        "thermal_pressure_start": [row["thermal_pressure_start"] for row in rows],
        "thermal_pressure_end": [row["thermal_pressure_end"] for row in rows],
        "peak_memory_mb": [row["peak_memory_mb"] for row in rows],
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
    excluded = {
        "thermal_pressure_start",
        "thermal_pressure_end",
    }
    per_metric = {
        name: summary["p99_over_p50"] < 1.4 if summary["p99_over_p50"] is not None else False
        for name, summary in summaries.items()
        if name not in excluded
    }
    return {"threshold": 1.4, "per_metric": per_metric, "passed": all(per_metric.values())}


def _thermal_drift(rows: list[dict[str, Any]]) -> dict[str, Any]:
    throughput = [row for row in rows if row["task_id"] == "throughput-512"]
    first = throughput[:5]
    last = throughput[-5:]
    first_p50 = _summarize([row["tokens_per_second"] for row in first])["p50"]
    last_p50 = _summarize([row["tokens_per_second"] for row in last])["p50"]
    pressure_start = [row["thermal_pressure_start"] for row in throughput]
    pressure_end = [row["thermal_pressure_end"] for row in throughput]
    if first_p50 is None or last_p50 is None:
        delta_pct = None
    else:
        delta_pct = ((last_p50 - first_p50) / first_p50) * 100.0 if first_p50 else None
    return {
        "task": "throughput-512",
        "first_5_p50_tokens_per_second": first_p50,
        "last_5_p50_tokens_per_second": last_p50,
        "last_vs_first_delta_pct": delta_pct,
        "thermal_pressure_start_sequence": pressure_start,
        "thermal_pressure_end_sequence": pressure_end,
        "thermal_pressure_max": (
            max([*pressure_start, *pressure_end]) if pressure_start or pressure_end else None
        ),
        "thermal_pressure_increased": bool(
            pressure_end and pressure_start and pressure_end[-1] > pressure_start[0]
        ),
        "material_degradation": delta_pct is not None and delta_pct <= -10.0,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    stats = report["statistics"]["overall"]
    lines = [
        "# Phase 1 M1 Max Canonical Report",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Protocol: `{report['measurement_protocol']}`",
        f"- Target/backend: `{report['target']}` / `{report['backend']}`",
        f"- Runtime: `{report['runtime']['runtime_name']}` `{report['runtime']['runtime_version']}`",
        f"- Ollama num_gpu: `{report['runtime']['extra'].get('num_gpu')}`",
        "- Telemetry: `partial-telemetry` (FNB58 wall-side only; no INA219 rail-side path)",
        f"- Model: `{report['runtime']['model_name']}`",
        f"- Model digest: `{report['runtime']['model_revision']}`",
        f"- Quantization: `{report['runtime']['quantization']}`",
        f"- Warmup sessions: `{report['session']['warmup_sessions']}`",
        f"- Valid measured sessions: `{report['session']['valid_measured_sessions']}`",
        f"- Headline FNB58 Wh/1000 tokens p50: `{_fmt(stats['fnb58_wh_per_1000_tokens']['p50'])}`",
        f"- Accuracy: `{report['accuracy']['score']:.3f}` "
        f"({report['accuracy']['passed']}/{report['accuracy']['total']})",
        f"- p99/p50 gate: `{report['statistics']['p99_over_p50_gate']['passed']}`",
        f"- Thermal drift, throughput first 5 vs last 5: "
        f"`{_fmt(report['statistics']['thermal_drift']['last_vs_first_delta_pct'])}%`",
        f"- Max measured thermal pressure: "
        f"`{_fmt(report['statistics']['thermal_drift']['thermal_pressure_max'])}`",
        "",
        "## GPU-Layer Sweep",
        "",
        "| num_gpu | tok/s | TTFT ms | Pressure start | Pressure end | Pressure flag |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report["gpu_layer_sweep"]["candidates"]:
        lines.append(
            f"| `{row['label']}` | {_fmt(row['tokens_per_second'])} | {_fmt(row['ttft_ms'])} | "
            f"{_fmt(row['thermal_pressure_start'])} | {_fmt(row['thermal_pressure_end'])} | "
            f"`{row['thermal_pressure_flag']}` |",
        )
    lines.extend(
        [
            "",
            "## Overall Statistics",
            "",
            "| Metric | Count | P50 | P95 | P99 | Stddev |",
            "|---|---:|---:|---:|---:|---:|",
        ],
    )
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
            "| Phase | Session | Task | Included | Pressure start/end | tok/s | TTFT ms | FNB58 Wh/1k |",
            "|---|---:|---|---|---:|---:|---:|---:|",
        ],
    )
    for row in report["invocations"]:
        lines.append(
            f"| {row['phase']} | {row['phase_index']} | `{row['task_id']}` | "
            f"`{not row['excluded_from_stats'] and not row['is_warmup']}` | "
            f"{_fmt(row['thermal_pressure_start'])}/{_fmt(row['thermal_pressure_end'])} | "
            f"{_fmt(row['tokens_per_second'])} | {_fmt(row['ttft_ms'])} | "
            f"{_fmt(row['energy']['fnb58_usb_c_charger_delivery']['wh_per_1000_tokens'])} |",
        )
    lines.extend(
        [
            "",
            "## Telemetry Note",
            "",
            "This is a partial-telemetry target. The FNB58 wall-side USB-C charger path is "
            "the authoritative energy source. powermetrics values are supplementary "
            "software estimates only and are not used for the headline Wh/1000 tokens.",
            "",
            "## Reproducibility",
            "",
            "```bash",
            report["reproducibility"]["command"],
            "```",
        ],
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_sweep_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 1 M1 Max GPU-Layer Sweep",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Model: `{report['model']}`",
        f"- Task: `{report['task']}`",
        f"- Selected num_gpu: `{report['selected']['label']}`",
        "",
        "| num_gpu | tok/s | TTFT ms | Pressure start | Pressure end | Pressure flag |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report["candidates"]:
        lines.append(
            f"| `{row['label']}` | {_fmt(row['tokens_per_second'])} | {_fmt(row['ttft_ms'])} | "
            f"{_fmt(row['thermal_pressure_start'])} | {_fmt(row['thermal_pressure_end'])} | "
            f"`{row['thermal_pressure_flag']}` |",
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


def _abort_if_thermal_pressure(snapshot: dict[str, Any], pressure_limit: int, label: str) -> None:
    pressure = int(snapshot["thermal_pressure_level"])
    print(
        f"M1 thermal pressure {label}: {pressure} ({snapshot['thermal_pressure_name']})",
        flush=True,
    )
    if pressure >= pressure_limit:
        raise RuntimeError(
            f"M1 Max thermal pressure {label} is heavy-or-worse: "
            f"{pressure} ({snapshot['thermal_pressure_name']})",
        )


def _compact_thermal(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at": snapshot["captured_at"],
        "thermal_pressure_level": snapshot["thermal_pressure_level"],
        "thermal_pressure_name": snapshot["thermal_pressure_name"],
    }


def _write_latest_pointer(pointer: Path, target: Path) -> None:
    pointer.parent.mkdir(parents=True, exist_ok=True)
    target_path = target if target.is_absolute() else ROOT / target
    pointer.write_text(
        json.dumps({"latest": str(target_path.resolve().relative_to(ROOT.resolve()))}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _run_text(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)


if __name__ == "__main__":
    main()
