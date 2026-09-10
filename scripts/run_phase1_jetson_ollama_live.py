#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the canonical Phase 1 Jetson Ollama benchmark with tegrastats telemetry."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
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
from signal_bench.phase1.measurement import integrate_joules
from signal_bench.phase1.runtime import GenerationRequest, GenerationResult, RuntimeMetadata
from signal_bench.phase1.workload import PromptCase, canonical_llm_workload

DEFAULT_JETSON_HOST = "<private-ip>"
DEFAULT_JETSON_USER = "jetson"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_WARMUPS = 5
DEFAULT_MEASURED = 20
DEFAULT_MAX_MEASURED_ATTEMPTS = 30
DEFAULT_TEMP_LIMIT_C = 85.0
DEFAULT_CONTEXT_LENGTH = 4096
PROTOCOL_ID = "n20_plus_5_v1"
RUN_ROOT = ROOT / "data" / "phase1" / "jetson" / "canonical"
SWEEP_ROOT = ROOT / "data" / "phase1" / "jetson" / "gpu-layer-sweep"

TEMP_RE = re.compile(r"\b([A-Za-z0-9_]+)@([0-9]+(?:\.[0-9]+)?)C\b")
VDD_IN_RE = re.compile(r"\bVDD_IN\s+([0-9]+(?:\.[0-9]+)?)mW(?:/([0-9]+(?:\.[0-9]+)?)mW)?\b")
GR3D_RE = re.compile(r"\bGR3D_FREQ\s+([0-9]+)%")
JETSON_CLOCK_CPU_RE = re.compile(r"^(cpu\d+):.*\bCurrentFreq=(\d+)\b")
JETSON_CLOCK_GPU_RE = re.compile(r"^GPU\b.*\bCurrentFreq=(\d+)\b")
JETSON_CLOCK_EMC_RE = re.compile(r"^EMC\b.*\bCurrentFreq=(\d+)\b")
SYSFS_CPU_RE = re.compile(r"/cpu(\d+)/cpufreq/scaling_cur_freq=(\d+)$")


def main() -> None:
    args = _parse_args()
    environment = collect_environment(ROOT)
    command = _repro_command(args)
    power_mode = _apply_maxn_super(args)
    identity = _jetson_identity(args)
    _abort_if_bad_power_mode(identity, power_mode)
    identity["clock_state"] = _capture_jetson_clock_state(args)
    model_info = _require_model_on_remote(args)
    workload = canonical_llm_workload(args.model)
    local_port = _free_port()
    tunnel = _start_ssh_tunnel(args, local_port)
    telemetry = TegrastatsMonitor(args)
    memory_monitor = RemoteMemoryMonitor(args)
    try:
        base_url = f"http://127.0.0.1:{local_port}"
        _wait_for_ollama(base_url)
        telemetry.start()
        memory_monitor.start()
        sweep = (
            _load_sweep_report(args)
            if args.use_sweep_report
            else _run_gpu_sweep(args, base_url, workload, telemetry)
        )
        selected_num_gpu = sweep["selected"]["num_gpu"]
        run_id = f"phase1-jetson-canonical-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
        run_root = args.output_root
        output_dir = run_root / run_id
        runtime = _runtime_metadata(args, identity, model_info, selected_num_gpu)
        session_started_at = dt.datetime.now(dt.UTC)
        invocation_rows: list[dict[str, Any]] = []

        try:
            for warmup_index in range(1, args.warmups + 1):
                invocation_rows.extend(
                    _run_task_suite(
                        args,
                        base_url,
                        workload.prompts,
                        telemetry,
                        memory_monitor,
                        phase="warmup",
                        phase_index=warmup_index,
                        is_warmup=True,
                        num_gpu=selected_num_gpu,
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
                    base_url,
                    workload.prompts,
                    telemetry,
                    memory_monitor,
                    phase="measured",
                    phase_index=measured_attempt,
                    is_warmup=False,
                    num_gpu=selected_num_gpu,
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
            telemetry.stop()
            memory_monitor.stop()

        _attach_measurements(invocation_rows, telemetry.samples, memory_monitor.samples)
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
            identity=identity,
            sweep=sweep,
            environment=environment,
            invocation_rows=invocation_rows,
            measured_rows=measured_rows,
            session_started_at=session_started_at,
            session_finished_at=session_finished_at,
            telemetry_samples=telemetry.samples,
            accuracy=accuracy,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "phase1-jetson-canonical-report.json"
        md_path = output_dir / "phase1-jetson-canonical-report.md"
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(_render_markdown(report), encoding="utf-8")
        _write_latest_pointer(run_root / "latest.json", json_path)
        print(f"Canonical JSON: {json_path}")
        print(f"Canonical Markdown: {md_path}")
    finally:
        memory_monitor.stop()
        telemetry.stop()
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()


class TegrastatsMonitor:
    """Stream tegrastats over SSH and timestamp parsed samples on the host."""

    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.samples: list[dict[str, Any]] = []

    def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            _ssh_command(self._args, "tegrastats --interval 1000"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.samples:
                return
            time.sleep(0.25)
        raise RuntimeError("tegrastats did not produce a parseable sample within 15 seconds.")

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def latest(self) -> dict[str, Any]:
        if not self.samples:
            raise RuntimeError("No tegrastats samples are available.")
        return self.samples[-1]

    def between(self, started_at: dt.datetime, finished_at: dt.datetime) -> list[dict[str, Any]]:
        start_ts = started_at.timestamp()
        finish_ts = finished_at.timestamp()
        return [
            sample for sample in self.samples if start_ts <= sample["timestamp_unix"] <= finish_ts
        ]

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop.is_set():
                return
            parsed = parse_tegrastats_line(line)
            if parsed is not None:
                parsed["timestamp_unix"] = time.time()
                parsed["captured_at"] = dt.datetime.now(dt.UTC).isoformat()
                parsed["raw"] = line.strip()
                self.samples.append(parsed)


class RemoteMemoryMonitor:
    """Poll aggregate remote Ollama RSS while the benchmark runs."""

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
                    'ps -eo rss=,comm= | awk \'$2=="ollama" || $2=="llama-server" {s+=$1} END{print s+0}\'',
                    timeout=10,
                )
                rss_kb = float(output.strip() or "0")
            except Exception:
                rss_kb = 0.0
            self.samples.append({"timestamp_unix": time.time(), "rss_mb": rss_kb / 1024.0})
            self._stop.wait(1.0)


def parse_tegrastats_line(line: str) -> dict[str, Any] | None:
    temps = {name: float(value) for name, value in TEMP_RE.findall(line)}
    power_match = VDD_IN_RE.search(line)
    gr3d_match = GR3D_RE.search(line)
    if not temps and power_match is None:
        return None
    vdd_in_w = float(power_match.group(1)) / 1000.0 if power_match else None
    vdd_in_avg_w = (
        float(power_match.group(2)) / 1000.0 if power_match and power_match.group(2) else None
    )
    return {
        "temps_c": temps,
        "vdd_in_w": vdd_in_w,
        "vdd_in_avg_w": vdd_in_avg_w,
        "gpu_util_pct": int(gr3d_match.group(1)) if gr3d_match else None,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jetson-host", default=DEFAULT_JETSON_HOST)
    parser.add_argument("--jetson-user", default=DEFAULT_JETSON_USER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--measured-runs", type=int, default=DEFAULT_MEASURED)
    parser.add_argument("--max-measured-attempts", type=int, default=DEFAULT_MAX_MEASURED_ATTEMPTS)
    parser.add_argument("--temp-limit-c", type=float, default=DEFAULT_TEMP_LIMIT_C)
    parser.add_argument("--context-length", type=int, default=DEFAULT_CONTEXT_LENGTH)
    parser.add_argument("--gpu-sweep", default="0,default")
    parser.add_argument("--output-root", type=Path, default=RUN_ROOT)
    parser.add_argument(
        "--use-sweep-report",
        type=Path,
        help="Use a prior Jetson GPU-layer sweep report and skip the sweep phase.",
    )
    return parser.parse_args()


def _repro_command(args: argparse.Namespace) -> str:
    command = (
        "uv run python scripts/run_phase1_jetson_ollama_live.py "
        f"--jetson-host {args.jetson_host} --jetson-user {args.jetson_user} "
        f"--model {args.model} --warmups {args.warmups} --measured-runs {args.measured_runs} "
        f"--gpu-sweep {args.gpu_sweep}"
    )
    if args.use_sweep_report:
        command += f" --use-sweep-report {args.use_sweep_report}"
    if args.output_root != RUN_ROOT:
        command += f" --output-root {args.output_root}"
    return command


def _apply_maxn_super(args: argparse.Namespace) -> dict[str, Any]:
    power_mode = _maxn_super_mode(args)
    output = _ssh_text(
        args,
        f"nvpmodel -m {power_mode['id']}; jetson_clocks; nvpmodel -q",
        sudo=True,
        timeout=120,
    )
    power_mode["apply_output"] = output
    if f"NV Power Mode: {power_mode['name']}" not in output:
        raise RuntimeError(f"nvpmodel did not confirm {power_mode['name']}:\n{output}")
    return power_mode


def _maxn_super_mode(args: argparse.Namespace) -> dict[str, Any]:
    text = _ssh_text(args, "readlink -f /etc/nvpmodel.conf; cat /etc/nvpmodel.conf", timeout=30)
    lines = text.splitlines()
    conf_path = lines[0].strip() if lines else "/etc/nvpmodel.conf"
    conf_text = "\n".join(lines[1:])
    match = re.search(r"<\s*POWER_MODEL\s+ID=(\d+)\s+NAME=MAXN_SUPER\s*>", conf_text)
    if match is None:
        raise RuntimeError(f"Could not find a MAXN_SUPER power model in {conf_path}.")
    return {
        "id": int(match.group(1)),
        "name": "MAXN_SUPER",
        "config_path": conf_path,
    }


def _jetson_identity(args: argparse.Namespace) -> dict[str, Any]:
    script = (
        "echo '--- nv_tegra_release ---'; "
        "cat /etc/nv_tegra_release 2>/dev/null || true; "
        "echo '--- os_release ---'; "
        "cat /etc/os-release 2>/dev/null || true; "
        "echo '--- kernel ---'; "
        "uname -r; "
        "echo '--- cuda ---'; "
        "nvcc --version 2>/dev/null || cat /usr/local/cuda/version.json 2>/dev/null || true; "
        "echo '--- nvpmodel ---'; "
        "nvpmodel -q; "
        "echo '--- ollama ---'; "
        "ollama --version 2>/dev/null || true"
    )
    return {
        "raw": _ssh_text(args, script, timeout=60),
        "captured_at": dt.datetime.now(dt.UTC).isoformat(),
    }


def _capture_jetson_clock_state(args: argparse.Namespace) -> dict[str, Any]:
    state: dict[str, Any] = {
        "captured_at": dt.datetime.now(dt.UTC).isoformat(),
        "source_preference": "jetson_clocks --show",
        "warnings": [],
    }
    warnings: list[str] = state["warnings"]

    try:
        show_raw = _ssh_text(args, "jetson_clocks --show", sudo=True, timeout=30)
        state["jetson_clocks_show"] = {
            "ok": True,
            "raw": show_raw,
            "parsed": _parse_jetson_clocks_show(show_raw),
        }
    except Exception as exc:
        warning = f"jetson_clocks --show capture failed: {exc}"
        warnings.append(warning)
        print(f"Warning: {warning}", file=sys.stderr, flush=True)
        state["jetson_clocks_show"] = {"ok": False, "error": str(exc)}

    try:
        sysfs_raw = _ssh_text(args, _jetson_sysfs_clock_script(), timeout=30)
        state["sysfs"] = _parse_jetson_sysfs_clocks(sysfs_raw)
    except Exception as exc:
        warning = f"Jetson sysfs clock capture failed: {exc}"
        warnings.append(warning)
        print(f"Warning: {warning}", file=sys.stderr, flush=True)
        state["sysfs"] = {"ok": False, "error": str(exc)}

    has_cpu = bool(
        state.get("jetson_clocks_show", {}).get("parsed", {}).get("cpu_current_freq_khz")
    ) or bool(
        state.get("sysfs", {}).get("cpu_scaling_cur_freq_khz"),
    )
    has_gpu = state.get("jetson_clocks_show", {}).get("parsed", {}).get(
        "gpu_current_freq_hz"
    ) is not None or bool(
        state.get("sysfs", {}).get("gpu_cur_freq_hz"),
    )
    if has_cpu and has_gpu:
        state["status"] = "ok"
    elif has_cpu or has_gpu:
        state["status"] = "partial"
        warning = "Jetson clock capture only recorded one of CPU/GPU clock state."
        warnings.append(warning)
        print(f"Warning: {warning}", file=sys.stderr, flush=True)
    else:
        state["status"] = "unavailable"
        warning = "Jetson clock capture did not record CPU or GPU clock state."
        warnings.append(warning)
        print(f"Warning: {warning}", file=sys.stderr, flush=True)
    return state


def _parse_jetson_clocks_show(raw: str) -> dict[str, Any]:
    cpu_current_freq_khz: dict[str, int] = {}
    gpu_current_freq_hz: int | None = None
    emc_current_freq_hz: int | None = None
    for line in raw.splitlines():
        cpu_match = JETSON_CLOCK_CPU_RE.search(line)
        if cpu_match:
            cpu_current_freq_khz[cpu_match.group(1)] = int(cpu_match.group(2))
            continue
        gpu_match = JETSON_CLOCK_GPU_RE.search(line)
        if gpu_match:
            gpu_current_freq_hz = int(gpu_match.group(1))
            continue
        emc_match = JETSON_CLOCK_EMC_RE.search(line)
        if emc_match:
            emc_current_freq_hz = int(emc_match.group(1))
    return {
        "cpu_current_freq_khz": cpu_current_freq_khz,
        "gpu_current_freq_hz": gpu_current_freq_hz,
        "emc_current_freq_hz": emc_current_freq_hz,
    }


def _jetson_sysfs_clock_script() -> str:
    return (
        "echo __CPU_SCALING_CUR_FREQ_KHZ__; "
        "for p in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do "
        '[ -r "$p" ] && printf \'%s=%s\\n\' "$p" "$(cat "$p")"; '
        "done; "
        "echo __DEVFREQ_CUR_FREQ_HZ__; "
        "find /sys/devices -path '*devfreq*' -name cur_freq -print 2>/dev/null | "
        "while IFS= read -r p; do "
        'v=$(cat "$p" 2>/dev/null || true); '
        '[ -n "$v" ] && printf \'%s=%s\\n\' "$p" "$v"; '
        "done"
    )


def _parse_jetson_sysfs_clocks(raw: str) -> dict[str, Any]:
    cpu_scaling_cur_freq_khz: dict[str, int] = {}
    devfreq_cur_freq_hz: dict[str, int] = {}
    gpu_cur_freq_hz: dict[str, int] = {}
    section: str | None = None
    for line in raw.splitlines():
        if line == "__CPU_SCALING_CUR_FREQ_KHZ__":
            section = "cpu"
            continue
        if line == "__DEVFREQ_CUR_FREQ_HZ__":
            section = "devfreq"
            continue
        if "=" not in line:
            continue
        key, value = line.rsplit("=", 1)
        try:
            parsed_value = int(value)
        except ValueError:
            continue
        if section == "cpu":
            match = SYSFS_CPU_RE.search(line)
            cpu_name = f"cpu{match.group(1)}" if match else key
            cpu_scaling_cur_freq_khz[cpu_name] = parsed_value
        elif section == "devfreq":
            devfreq_cur_freq_hz[key] = parsed_value
            if "gpu" in key.lower():
                gpu_cur_freq_hz[key] = parsed_value
    return {
        "ok": True,
        "raw": raw,
        "cpu_scaling_cur_freq_khz": cpu_scaling_cur_freq_khz,
        "devfreq_cur_freq_hz": devfreq_cur_freq_hz,
        "gpu_cur_freq_hz": gpu_cur_freq_hz,
    }


def _abort_if_bad_power_mode(identity: dict[str, Any], expected: dict[str, Any]) -> None:
    text = identity["raw"]
    expected_line = f"NV Power Mode: {expected['name']}"
    if expected_line not in text:
        raise RuntimeError(f"{expected['name']} was not clearly confirmed by nvpmodel:\n{text}")


def _require_model_on_remote(args: argparse.Namespace) -> dict[str, Any]:
    try:
        output = _ssh_text(args, f"ollama show {args.model} --json", timeout=30)
    except RuntimeError:
        output = ""
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        show = _ssh_text(args, f"ollama show {args.model}", timeout=30)
        tags = _ssh_text(args, "ollama list", timeout=30)
        digest = _digest_from_ollama_list(tags, args.model)
        if digest is None:
            raise RuntimeError(
                f"Could not confirm installed Jetson model {args.model!r}:\n{tags}"
            ) from None
        return {
            "name": args.model,
            "digest": digest,
            "details": _parse_ollama_show_details(show),
            "raw_show": show,
            "raw_list": tags,
        }


def _digest_from_ollama_list(text: str, model: str) -> str | None:
    for line in text.splitlines():
        columns = line.split()
        if len(columns) >= 2 and columns[0] == model:
            return columns[1]
    return None


def _parse_ollama_show_details(text: str) -> dict[str, str]:
    details: dict[str, str] = {}
    mapping = {
        "architecture": "architecture",
        "parameters": "parameter_size",
        "context length": "context_length",
        "embedding length": "embedding_length",
        "quantization": "quantization_level",
    }
    for line in text.splitlines():
        stripped = line.strip()
        for label, key in mapping.items():
            if stripped.startswith(label):
                details[key] = stripped.removeprefix(label).strip()
                break
    return details


def _runtime_metadata(
    args: argparse.Namespace,
    identity: dict[str, Any],
    model_info: dict[str, Any],
    num_gpu: int | None,
) -> RuntimeMetadata:
    details = model_info.get("details") or {}
    return RuntimeMetadata(
        runtime_name="ollama",
        runtime_version=_extract_line(identity["raw"], "ollama version") or "unknown",
        target_name="jetson-orin-nano-super",
        backend="jetson-ollama-cuda",
        model_name=str(model_info.get("model") or model_info.get("name") or args.model),
        model_revision=str(model_info.get("digest") or "unknown"),
        quantization=details.get("quantization_level"),
        model_bytes=int(model_info["size"]) if model_info.get("size") else None,
        extra={
            "measurement_protocol": PROTOCOL_ID,
            "context_length": args.context_length,
            "num_gpu": "default" if num_gpu is None else num_gpu,
            "telemetry_basis": "partial_real_tegrastats_vdd_in",
            "model_source": "ollama-local",
            "thermal_source": "tegrastats",
            "power_source": "tegrastats VDD_IN / onboard INA3221",
            "cooling_policy": "Jetson Orin Nano Super dev kit cooling; MAXN_SUPER and jetson_clocks applied.",
            "runtime_version_caveat": (
                "Jetson uses target-native Ollama 0.30.10 from the official JetPack ARM64 path; "
                "Pi 5 and M1 Max canonical runs used Ollama 0.30.7. Model digest and protocol match."
            ),
        },
    )


def _load_sweep_report(args: argparse.Namespace) -> dict[str, Any]:
    path = args.use_sweep_report
    if path is None:
        raise RuntimeError("No sweep report path was provided.")
    if not path.is_absolute():
        path = ROOT / path
    report = json.loads(path.read_text(encoding="utf-8"))
    selected = report.get("selected") or {}
    if selected.get("label") != "default" or selected.get("num_gpu") is not None:
        raise RuntimeError(f"Prior sweep did not select Ollama default CUDA: {path}")
    report["reused_for_canonical_rerun"] = True
    report["source_report"] = str(path.relative_to(ROOT))
    return report


def _run_gpu_sweep(
    args: argparse.Namespace,
    base_url: str,
    workload: Any,
    telemetry: TegrastatsMonitor,
) -> dict[str, Any]:
    run_id = f"jetson-gpu-layer-sweep-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    output_dir = SWEEP_ROOT / run_id
    candidates = _gpu_candidates(args.gpu_sweep)
    prompt = next(item for item in workload.prompts if item.prompt_id == "throughput-512")
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        label = "default" if candidate is None else str(candidate)
        print(f"GPU sweep candidate num_gpu={label}", flush=True)
        start_sample = telemetry.latest()
        result = _generate(base_url, args.model, prompt, args=args, num_gpu=candidate)
        end_sample = telemetry.latest()
        window = telemetry.between(result.started_at, result.finished_at)
        energy = _energy_from_samples(
            window, result.tokens_out, result.started_at, result.finished_at
        )
        results.append(
            {
                "num_gpu": candidate,
                "label": label,
                "tokens_per_second": result.tokens_per_second,
                "ttft_ms": result.first_token_ms,
                "tokens_out": result.tokens_out,
                "duration_ms": result.duration_ms,
                "vdd_in_avg_w": energy["avg_power_w"],
                "wh_per_1000_tokens": energy["wh_per_1000_tokens"],
                "temps_start_c": start_sample["temps_c"],
                "temps_end_c": end_sample["temps_c"],
                "max_temp_end_c": _max_temp(end_sample),
                "gpu_util_pct_end": end_sample.get("gpu_util_pct"),
                "temperature_flag": _max_temp(end_sample) is not None
                and _max_temp(end_sample) > args.temp_limit_c,
            },
        )
    valid = [row for row in results if not row["temperature_flag"]]
    if not valid:
        raise RuntimeError("All Jetson sweep candidates exceeded the temperature limit.")
    selected = max(valid, key=lambda row: row["tokens_per_second"])
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "target": "jetson-orin-nano-super",
        "model": args.model,
        "task": "throughput-512",
        "temp_limit_c": args.temp_limit_c,
        "candidates": results,
        "selected": selected,
        "note": "Sweep uses the 512-token throughput task only. Energy source is tegrastats VDD_IN.",
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
    base_url: str,
    prompts: tuple[PromptCase, ...],
    telemetry: TegrastatsMonitor,
    memory_monitor: RemoteMemoryMonitor,
    *,
    phase: str,
    phase_index: int,
    is_warmup: bool,
    num_gpu: int | None,
) -> list[dict[str, Any]]:
    rows = []
    print(f"Starting {phase} session {phase_index} ({len(prompts)} tasks).", flush=True)
    for prompt in prompts:
        start_sample = telemetry.latest()
        _abort_if_temp(
            start_sample, args.temp_limit_c, f"before {phase} {phase_index} {prompt.prompt_id}"
        )
        result = _generate(base_url, args.model, prompt, args=args, num_gpu=num_gpu)
        end_sample = telemetry.latest()
        peak_memory_mb = memory_monitor.peak_between(result.started_at, result.finished_at)
        exclusion_reasons: list[str] = []
        max_end = _max_temp(end_sample)
        if is_warmup and max_end is not None and max_end > args.temp_limit_c:
            raise RuntimeError(f"Jetson exceeded {args.temp_limit_c} C during warmup: {max_end} C")
        if not is_warmup and max_end is not None and max_end > args.temp_limit_c:
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
                "tegrastats_start": _compact_sample(start_sample),
                "tegrastats_end": _compact_sample(end_sample),
                "temps_start_c": start_sample["temps_c"],
                "temps_end_c": end_sample["temps_c"],
                "max_temp_start_c": _max_temp(start_sample),
                "max_temp_end_c": max_end,
                "gpu_util_pct_start": start_sample.get("gpu_util_pct"),
                "gpu_util_pct_end": end_sample.get("gpu_util_pct"),
                "excluded_from_stats": bool(exclusion_reasons),
                "exclusion_reasons": exclusion_reasons,
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
    telemetry_samples: list[dict[str, Any]],
    memory_samples: list[dict[str, float]],
) -> None:
    for row in rows:
        started_at = dt.datetime.fromisoformat(row["started_at"])
        finished_at = dt.datetime.fromisoformat(row["finished_at"])
        window = [
            s
            for s in telemetry_samples
            if started_at.timestamp() <= s["timestamp_unix"] <= finished_at.timestamp()
        ]
        energy = _energy_from_samples(window, row["tokens_out"], started_at, finished_at)
        row["energy"] = {"tegrastats_vdd_in": energy}
        row["telemetry_status"] = {
            "label": "partial-telemetry",
            "reason": "Jetson uses onboard INA3221 VDD_IN via tegrastats; external INA219 is not attached.",
            "cross_check": "not_applicable_no_external_wall_meter",
        }
        row["sample_counts"] = {"tegrastats": len(window)}
        row["peak_memory_mb"] = row["peak_memory_mb"] or _peak_memory_between(
            memory_samples, started_at, finished_at
        )


def _energy_from_samples(
    samples: list[dict[str, Any]],
    tokens_out: int,
    started_at: dt.datetime,
    finished_at: dt.datetime,
) -> dict[str, float | int | None]:
    series = tuple(
        (sample["timestamp_unix"] - started_at.timestamp(), sample["vdd_in_w"])
        for sample in samples
        if sample.get("vdd_in_w") is not None
    )
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
    identity: dict[str, Any],
    sweep: dict[str, Any],
    environment: Any,
    invocation_rows: list[dict[str, Any]],
    measured_rows: list[dict[str, Any]],
    session_started_at: dt.datetime,
    session_finished_at: dt.datetime,
    telemetry_samples: list[dict[str, Any]],
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
        "schema_version": 1,
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "target": "jetson-orin-nano-super",
        "backend": "jetson-ollama-cuda",
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
            "temp_limit_c": args.temp_limit_c,
            "excluded_for_temperature": sum(
                1
                for row in invocation_rows
                if f"temperature_gt_{args.temp_limit_c:g}c" in row["exclusion_reasons"]
            ),
        },
        "telemetry": {
            "label": "partial-telemetry",
            "basis": "real_onboard_ina3221_tegrastats_vdd_in",
            "energy_is_mock": False,
            "sources": {
                "tegrastats_vdd_in": "Jetson onboard INA3221 total board input; headline Wh/1000 token source",
            },
            "unavailable_sources": {
                "fnb58": "Not inline on stock Jetson barrel-jack power path.",
                "ina219": "External INA219 is not attached; onboard INA3221 replaces it for this target.",
            },
            "cross_check": "not_applicable_no_external_wall_meter",
            "total_samples": {"tegrastats": len(telemetry_samples)},
        },
        "reproducibility_caveats": {
            "ollama_version": (
                "Jetson uses target-native Ollama 0.30.10 from the official JetPack ARM64 path; "
                "Pi 5 and M1 Max canonical runs used Ollama 0.30.7. Model digest and protocol match."
            ),
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
        "jetson_identity_start": identity,
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
        "tegrastats_vdd_in_wh_per_1000_tokens": [
            row["energy"]["tegrastats_vdd_in"]["wh_per_1000_tokens"] for row in rows
        ],
        "tegrastats_vdd_in_joules_per_token": [
            row["energy"]["tegrastats_vdd_in"]["joules_per_token"] for row in rows
        ],
        "vdd_in_avg_w": [row["energy"]["tegrastats_vdd_in"]["avg_power_w"] for row in rows],
        "max_temp_start_c": [row["max_temp_start_c"] for row in rows],
        "max_temp_end_c": [row["max_temp_end_c"] for row in rows],
        "peak_memory_mb": [row["peak_memory_mb"] for row in rows],
        "gpu_util_pct_end": [row["gpu_util_pct_end"] for row in rows],
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
    p99 = _percentile(clean, 0.99)
    return {
        "count": len(clean),
        "p50": p50,
        "p95": _percentile(clean, 0.95),
        "p99": p99,
        "stddev": statistics.stdev(clean) if len(clean) >= 2 else 0.0,
        "mean": statistics.mean(clean),
        "min": min(clean),
        "max": max(clean),
        "p99_over_p50": (p99 / p50) if p50 not in (None, 0) else None,
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
    excluded = {"max_temp_start_c", "max_temp_end_c", "gpu_util_pct_end"}
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
    if first_p50 is None or last_p50 is None:
        delta_pct = None
    else:
        delta_pct = ((last_p50 - first_p50) / first_p50) * 100.0 if first_p50 else None
    end_temps = [row["max_temp_end_c"] for row in throughput if row["max_temp_end_c"] is not None]
    return {
        "task": "throughput-512",
        "first_5_p50_tokens_per_second": first_p50,
        "last_5_p50_tokens_per_second": last_p50,
        "last_vs_first_delta_pct": delta_pct,
        "max_temp_end_c_sequence": end_temps,
        "max_temp_end_c": max(end_temps) if end_temps else None,
        "material_degradation": delta_pct is not None and delta_pct <= -10.0,
    }


def _classification_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = []
    for row in rows:
        expected = row.get("accuracy_expected") or []
        if not expected:
            continue
        observed = str(row["output"]).strip().lower()
        passed = all(str(item).lower() in observed for item in expected)
        scored.append(
            {
                "task_id": row["task_id"],
                "phase_index": row["phase_index"],
                "expected": expected,
                "observed": observed,
                "passed": passed,
            }
        )
    total = len(scored)
    passed_count = sum(1 for item in scored if item["passed"])
    return {
        "metric": "classification_contains_all",
        "passed": passed_count,
        "total": total,
        "score": passed_count / total if total else None,
        "prompt_scores": scored,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    stats = report["statistics"]["overall"]
    lines = [
        "# Phase 1 Jetson Canonical Report",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Protocol: `{report['measurement_protocol']}`",
        f"- Target/backend: `{report['target']}` / `{report['backend']}`",
        f"- Runtime: `{report['runtime']['runtime_name']}` `{report['runtime']['runtime_version']}`",
        f"- Ollama num_gpu: `{report['runtime']['extra'].get('num_gpu')}`",
        "- Telemetry: `partial-telemetry` (tegrastats VDD_IN onboard INA3221; no external INA219)",
        f"- Model: `{report['runtime']['model_name']}`",
        f"- Model digest: `{report['runtime']['model_revision']}`",
        f"- Quantization: `{report['runtime']['quantization']}`",
        "- Runtime caveat: `Jetson Ollama 0.30.10; Pi 5 and M1 Max Ollama 0.30.7; same model digest and protocol`",
        f"- Warmup sessions: `{report['session']['warmup_sessions']}`",
        f"- Valid measured sessions: `{report['session']['valid_measured_sessions']}`",
        f"- Headline VDD_IN Wh/1000 tokens p50: `{_fmt(stats['tegrastats_vdd_in_wh_per_1000_tokens']['p50'])}`",
        f"- Accuracy: `{_fmt(report['accuracy']['score'])}` ({report['accuracy']['passed']}/{report['accuracy']['total']})",
        f"- p99/p50 gate: `{report['statistics']['p99_over_p50_gate']['passed']}`",
        f"- Thermal drift, throughput first 5 vs last 5: `{_fmt(report['statistics']['thermal_drift']['last_vs_first_delta_pct'])}%`",
        f"- Max measured end temperature: `{_fmt(report['statistics']['thermal_drift']['max_temp_end_c'])} C`",
        "",
        "## GPU-Layer Sweep",
        "",
        "| num_gpu | tok/s | TTFT ms | VDD_IN W | End temp C | GPU util % |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["gpu_layer_sweep"]["candidates"]:
        lines.append(
            f"| `{row['label']}` | {_fmt(row['tokens_per_second'])} | {_fmt(row['ttft_ms'])} | "
            f"{_fmt(row['vdd_in_avg_w'])} | {_fmt(row['max_temp_end_c'])} | {_fmt(row['gpu_util_pct_end'])} |"
        )
    lines.extend(
        ["", "## Overall Statistics", "", _stats_table(stats), "", "## Task Statistics", ""]
    )
    for task_id, task_stats in report["statistics"]["by_task"].items():
        lines.extend([f"### `{task_id}`", "", _stats_table(task_stats), ""])
    lines.extend(
        [
            "## Telemetry Note",
            "",
            "This is a partial-telemetry target. tegrastats VDD_IN from the onboard INA3221 is the headline energy source. FNB58 is not inline on the stock barrel-jack power path.",
            "",
            "## Reproducibility",
            "",
            "```bash",
            report["reproducibility"]["command"],
            "```",
            "",
        ],
    )
    return "\n".join(lines)


def _render_sweep_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 1 Jetson GPU-Layer Sweep",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Model: `{report['model']}`",
        f"- Task: `{report['task']}`",
        f"- Selected num_gpu: `{report['selected']['label']}`",
        "",
        "| num_gpu | tok/s | TTFT ms | VDD_IN W | End temp C | GPU util % |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["candidates"]:
        lines.append(
            f"| `{row['label']}` | {_fmt(row['tokens_per_second'])} | {_fmt(row['ttft_ms'])} | "
            f"{_fmt(row['vdd_in_avg_w'])} | {_fmt(row['max_temp_end_c'])} | {_fmt(row['gpu_util_pct_end'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def _stats_table(stats: dict[str, dict[str, float | int | None]]) -> str:
    lines = ["| Metric | Count | P50 | P95 | P99 | Stddev |", "|---|---:|---:|---:|---:|---:|"]
    for name, summary in stats.items():
        lines.append(
            f"| `{name}` | {summary['count']} | {_fmt(summary['p50'])} | {_fmt(summary['p95'])} | "
            f"{_fmt(summary['p99'])} | {_fmt(summary['stddev'])} |"
        )
    return "\n".join(lines)


def _is_stats_row(row: dict[str, Any]) -> bool:
    return row["phase"] == "measured" and not row["excluded_from_stats"]


def _valid_measured_session_count(rows: list[dict[str, Any]]) -> int:
    sessions = {row["phase_index"] for row in rows if row["phase"] == "measured"}
    return len(sessions)


def _compact_sample(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at": sample.get("captured_at"),
        "temps_c": sample.get("temps_c", {}),
        "vdd_in_w": sample.get("vdd_in_w"),
        "gpu_util_pct": sample.get("gpu_util_pct"),
    }


def _max_temp(sample: dict[str, Any]) -> float | None:
    temps = sample.get("temps_c") or {}
    return max(temps.values()) if temps else None


def _abort_if_temp(sample: dict[str, Any], limit_c: float, label: str) -> None:
    max_temp = _max_temp(sample)
    if max_temp is not None and max_temp > limit_c:
        raise RuntimeError(f"Jetson temperature before {label} exceeds {limit_c} C: {max_temp} C")


def _peak_memory_between(
    samples: list[dict[str, float]], started_at: dt.datetime, finished_at: dt.datetime
) -> float | None:
    start_ts = started_at.timestamp()
    finish_ts = finished_at.timestamp()
    values = [
        sample["rss_mb"] for sample in samples if start_ts <= sample["timestamp_unix"] <= finish_ts
    ]
    return max(values) if values else None


def _ssh_command(args: argparse.Namespace, remote_command: str) -> list[str]:
    return [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        f"{args.jetson_user}@{args.jetson_host}",
        remote_command,
    ]


def _ssh_text(
    args: argparse.Namespace,
    remote_command: str,
    *,
    sudo: bool = False,
    timeout: int = 30,
) -> str:
    command_text = remote_command
    if sudo:
        command_text = f"sudo -n bash -lc {json.dumps(remote_command)}"
    completed = subprocess.run(
        _ssh_command(args, command_text),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def _start_ssh_tunnel(args: argparse.Namespace, local_port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "ssh",
            "-N",
            "-L",
            f"{local_port}:127.0.0.1:11434",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{args.jetson_user}@{args.jetson_host}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


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


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _extract_line(text: str, needle: str) -> str | None:
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return None


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
