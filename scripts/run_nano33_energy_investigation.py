# SPDX-License-Identifier: Apache-2.0
"""Run Nano 33 energy investigation Nano 33 BLE Sense Rev2 energy investigation cells.

This script stages separate Nano 33 KWS firmware variants and writes all new
measurement artifacts under ``data/nano33_energy/nano33``. It deliberately does not
modify the Post 1 data matrix or canonical Tier 1 artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import importlib.util
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import serial

from signal_bench import __version__
from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.sources.bme280 import Bme280Config, Bme280Source
from signal_bench.telemetry.sources.fnirsi import FnirsiSource, FnirsiSourceConfig
from signal_bench.telemetry.sources.ina219 import Ina219Config, Ina219Source

ROOT = Path(__file__).resolve().parents[1]
P3_SCRIPT = ROOT / "scripts" / "run_p3_mcu_matrix.py"
BUILD_ROOT = ROOT / "build" / "nano33_energy-nano33"
DATA_ROOT = ROOT / "data" / "nano33_energy" / "nano33"
FNB58_ADDRESS = "<fnb58-address>"
CANONICAL_NANO_KWS_WH_PER_1000 = 0.002664702954943131
CANONICAL_NANO_KWS_VARIANCE_BAND = 0.15


def _load_p3_module() -> Any:
    spec = importlib.util.spec_from_file_location("p3_mcu_matrix", P3_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {P3_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["p3_mcu_matrix"] = module
    spec.loader.exec_module(module)
    return module


P3 = _load_p3_module()


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    build_flags: tuple[str, ...] = ()
    lib_deps: tuple[str, ...] = ()
    description: str = ""


VARIANTS: dict[str, Variant] = {
    "baseline": Variant(
        name="baseline",
        build_flags=('-DSIGNAL_BENCH_NANO33_ENERGY_VARIANT=\\"baseline\\"',),
        description="Post 1-equivalent KWS firmware: no BLE API calls and no explicit sensor init.",
    ),
    "radio-idle": Variant(
        name="radio-idle",
        build_flags=(
            '-DSIGNAL_BENCH_NANO33_ENERGY_VARIANT=\\"radio-idle\\"',
            "-DSIGNAL_BENCH_BLE_IDLE",
        ),
        lib_deps=("arduino-libraries/ArduinoBLE@^1.4.1",),
        description="Initializes BLE stack and local name, but does not advertise.",
    ),
    "radio-advertise": Variant(
        name="radio-advertise",
        build_flags=(
            '-DSIGNAL_BENCH_NANO33_ENERGY_VARIANT=\\"radio-advertise\\"',
            "-DSIGNAL_BENCH_BLE_ADVERTISE",
        ),
        lib_deps=("arduino-libraries/ArduinoBLE@^1.4.1",),
        description="Initializes BLE stack and advertises a simple local name.",
    ),
    "peripherals": Variant(
        name="peripherals",
        build_flags=(
            '-DSIGNAL_BENCH_NANO33_ENERGY_VARIANT=\\"peripherals\\"',
            "-DSIGNAL_BENCH_PERIPHERALS",
        ),
        lib_deps=(
            "arduino-libraries/Arduino_BMI270_BMM150@^1.2.2",
            "arduino-libraries/Arduino_HS300x@^1.0.0",
            "arduino-libraries/Arduino_LPS22HB@^1.0.2",
        ),
        description="Initializes typical onboard IMU and environmental sensor libraries.",
    ),
    "dcdc-on": Variant(
        name="dcdc-on",
        build_flags=(
            '-DSIGNAL_BENCH_NANO33_ENERGY_VARIANT=\\"dcdc-on\\"',
            "-DSIGNAL_BENCH_DCDC_ON",
        ),
        description="Forces nRF52840 REG1 DC-DC enable before model initialization.",
    ),
    "dcdc-off": Variant(
        name="dcdc-off",
        build_flags=(
            '-DSIGNAL_BENCH_NANO33_ENERGY_VARIANT=\\"dcdc-off\\"',
            "-DSIGNAL_BENCH_DCDC_OFF",
        ),
        description="Forces nRF52840 REG1 DC-DC disable before model initialization.",
    ),
}


NANO33_ENERGY_INCLUDE_INJECTION = r"""

#include <nrf.h>

#ifdef SIGNAL_BENCH_BLE_IDLE
#include <ArduinoBLE.h>
#endif

#ifdef SIGNAL_BENCH_BLE_ADVERTISE
#include <ArduinoBLE.h>
#endif

#ifdef SIGNAL_BENCH_PERIPHERALS
#include <Arduino_BMI270_BMM150.h>
#include <Arduino_HS300x.h>
#include <Arduino_LPS22HB.h>
#endif
"""


NANO33_ENERGY_SUPPORT_INJECTION = r"""

#ifndef SIGNAL_BENCH_NANO33_ENERGY_VARIANT
#define SIGNAL_BENCH_NANO33_ENERGY_VARIANT "unknown"
#endif

static bool nano33_energy_ble_ok = false;
static bool nano33_energy_ble_advertising = false;
static bool nano33_energy_imu_ok = false;
static bool nano33_energy_hs300x_ok = false;
static bool nano33_energy_lps22hb_ok = false;

static void nano33_energy_configure_power() {
#ifdef SIGNAL_BENCH_DCDC_ON
  NRF_POWER->DCDCEN = 1;
#endif
#ifdef SIGNAL_BENCH_DCDC_OFF
  NRF_POWER->DCDCEN = 0;
#endif
}

static void nano33_energy_init_ble() {
#if defined(SIGNAL_BENCH_BLE_IDLE) || defined(SIGNAL_BENCH_BLE_ADVERTISE)
  nano33_energy_ble_ok = BLE.begin();
  if (nano33_energy_ble_ok) {
    BLE.setLocalName("sb-nano33-nano33_energy");
    BLE.setDeviceName("sb-nano33-nano33_energy");
  }
#endif
#ifdef SIGNAL_BENCH_BLE_ADVERTISE
  if (nano33_energy_ble_ok) {
    nano33_energy_ble_advertising = BLE.advertise();
  }
#endif
}

static void nano33_energy_init_peripherals() {
#ifdef SIGNAL_BENCH_PERIPHERALS
  nano33_energy_imu_ok = IMU.begin();
  nano33_energy_hs300x_ok = HS300x.begin();
  nano33_energy_lps22hb_ok = BARO.begin();
#endif
}

static void nano33_energy_poll() {
#if defined(SIGNAL_BENCH_BLE_IDLE) || defined(SIGNAL_BENCH_BLE_ADVERTISE)
  if (nano33_energy_ble_ok) {
    BLE.poll();
  }
#endif
}

static bool nano33_energy_parse_seconds_command(const char *line, const char *command, float *seconds) {
  while (*line == ' ' || *line == '\t') {
    line++;
  }
  const size_t command_len = strlen(command);
  if (strncmp(line, command, command_len) != 0) {
    return false;
  }
  if (line[command_len] != '\0' && line[command_len] != ' ' && line[command_len] != '\t') {
    return false;
  }
  const char *cursor = line + command_len;
  while (*cursor == ' ' || *cursor == '\t') {
    cursor++;
  }
  uint32_t whole = 0;
  uint32_t frac = 0;
  uint32_t frac_scale = 1;
  bool saw_digit = false;
  while (*cursor >= '0' && *cursor <= '9') {
    saw_digit = true;
    whole = whole * 10 + static_cast<uint32_t>(*cursor - '0');
    cursor++;
  }
  if (*cursor == '.') {
    cursor++;
    while (*cursor >= '0' && *cursor <= '9' && frac_scale < 1000) {
      saw_digit = true;
      frac = frac * 10 + static_cast<uint32_t>(*cursor - '0');
      frac_scale *= 10;
      cursor++;
    }
    while (*cursor >= '0' && *cursor <= '9') {
      cursor++;
    }
  }
  while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r') {
    cursor++;
  }
  if (!saw_digit || *cursor != '\0') {
    return false;
  }
  const float parsed = static_cast<float>(whole) + (static_cast<float>(frac) / static_cast<float>(frac_scale));
  if (parsed <= 0.0f) {
    return false;
  }
  *seconds = parsed;
  return true;
}

static void nano33_energy_emit_status() {
  SIGNAL_BENCH_SERIAL.print("STATUS_JSON ");
  SIGNAL_BENCH_SERIAL.print("{\"variant\":\"");
  SIGNAL_BENCH_SERIAL.print(SIGNAL_BENCH_NANO33_ENERGY_VARIANT);
  SIGNAL_BENCH_SERIAL.print("\",\"version\":\"");
  SIGNAL_BENCH_SERIAL.print(SIGNAL_BENCH_VERSION);
  SIGNAL_BENCH_SERIAL.print("\",\"system_core_clock_hz\":");
  SIGNAL_BENCH_SERIAL.print(SystemCoreClock);
  SIGNAL_BENCH_SERIAL.print(",\"hfclkstat\":");
  SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(NRF_CLOCK->HFCLKSTAT));
  SIGNAL_BENCH_SERIAL.print(",\"lfclkstat\":");
  SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(NRF_CLOCK->LFCLKSTAT));
  SIGNAL_BENCH_SERIAL.print(",\"dcdcen\":");
  SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(NRF_POWER->DCDCEN));
#ifdef NRF_POWER_DCDCEN0_DCDCEN_Msk
  SIGNAL_BENCH_SERIAL.print(",\"dcdcen0\":");
  SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(NRF_POWER->DCDCEN0));
#endif
  SIGNAL_BENCH_SERIAL.print(",\"ble_ok\":");
  SIGNAL_BENCH_SERIAL.print(nano33_energy_ble_ok ? "true" : "false");
  SIGNAL_BENCH_SERIAL.print(",\"ble_advertising\":");
  SIGNAL_BENCH_SERIAL.print(nano33_energy_ble_advertising ? "true" : "false");
  SIGNAL_BENCH_SERIAL.print(",\"imu_ok\":");
  SIGNAL_BENCH_SERIAL.print(nano33_energy_imu_ok ? "true" : "false");
  SIGNAL_BENCH_SERIAL.print(",\"hs300x_ok\":");
  SIGNAL_BENCH_SERIAL.print(nano33_energy_hs300x_ok ? "true" : "false");
  SIGNAL_BENCH_SERIAL.print(",\"lps22hb_ok\":");
  SIGNAL_BENCH_SERIAL.print(nano33_energy_lps22hb_ok ? "true" : "false");
  SIGNAL_BENCH_SERIAL.print(",\"arena_used\":");
  SIGNAL_BENCH_SERIAL.print(init_ok ? static_cast<unsigned long>(interpreter->arena_used_bytes()) : 0UL);
  SIGNAL_BENCH_SERIAL.println("}");
}

static void nano33_energy_idle_busy(float seconds) {
  const uint32_t duration_us = static_cast<uint32_t>(seconds * 1000000.0f);
  const uint32_t start_us = micros();
  while (micros() - start_us < duration_us) {
    nano33_energy_poll();
    asm volatile("");
  }
  SIGNAL_BENCH_SERIAL.print("IDLE_DONE busy ");
  SIGNAL_BENCH_SERIAL.println(seconds, 3);
}

static void nano33_energy_idle_sleep(float seconds) {
  const uint32_t duration_ms = static_cast<uint32_t>(seconds * 1000.0f);
  const uint32_t start_ms = millis();
  while (millis() - start_ms < duration_ms) {
    nano33_energy_poll();
    delay(1);
  }
  SIGNAL_BENCH_SERIAL.print("IDLE_DONE sleep ");
  SIGNAL_BENCH_SERIAL.println(seconds, 3);
}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=P3.TARGET_CONFIGS["nano33"].serial_port)
    parser.add_argument("--fnb58-address", default=FNB58_ADDRESS)
    parser.add_argument("--sample-count", type=int, default=12)
    parser.add_argument("--measurement-s", type=float, default=32.0)
    parser.add_argument("--probe-iterations", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--measured", type=int, default=20)
    parser.add_argument(
        "--phase",
        choices=("build", "phase-a", "idle", "duty", "radio", "peripheral", "dcdc", "all"),
        default="build",
    )
    parser.add_argument("--variants", nargs="+", choices=sorted(VARIANTS), default=None)
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--require-fnb58", action="store_true", default=False)
    parser.add_argument("--idle-seconds", type=float, default=60.0)
    parser.add_argument("--paced-delay-s", type=float, default=0.25)
    args = parser.parse_args()

    os.environ.setdefault("BLINKA_MCP2221", "1")
    os.environ.setdefault("SIGNAL_BENCH_REAL_I2C", "1")
    os.environ.setdefault("FNB58_TRANSPORT", "ble")

    if args.phase == "build":
        summaries = [_build_variant(variant, args) for variant in (args.variants or ["baseline"])]
        print(json.dumps(summaries, indent=2, sort_keys=True))
        return 0 if all(item["build"]["ok"] for item in summaries) else 1

    run_dir = DATA_ROOT / dt.datetime.now(dt.UTC).strftime("nano33_energy-nano33-%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(_run_phase(args, run_dir))
    _write_report(run_dir, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") != "failed" else 1


async def _run_phase(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    if args.phase == "phase-a":
        result = await _run_reproduction(args, run_dir)
        if not result["phase_a_pass"]:
            result["status"] = "failed"
        return result
    if args.phase == "idle":
        return await _run_idle_floor(args, run_dir)
    if args.phase == "duty":
        return await _run_duty_cycle(args, run_dir)
    if args.phase == "radio":
        return await _run_variant_cells(
            args,
            run_dir,
            _selected_variants(args, ["baseline", "radio-idle", "radio-advertise"]),
            "radio-sweep",
        )
    if args.phase == "peripheral":
        return await _run_variant_cells(
            args, run_dir, _selected_variants(args, ["baseline", "peripherals"]), "peripheral-sweep"
        )
    if args.phase == "dcdc":
        return await _run_variant_cells(
            args, run_dir, _selected_variants(args, ["dcdc-off", "dcdc-on"]), "dcdc-sweep"
        )
    if args.phase == "all":
        phase_a = await _run_reproduction(args, run_dir / "phase-a")
        if not phase_a["phase_a_pass"]:
            return {
                "status": "failed",
                "reason": "Phase A reproduction gate failed",
                "phase_a": phase_a,
            }
        idle = await _run_idle_floor(_diagnostic_args(args), run_dir / "idle")
        duty = await _run_duty_cycle(_diagnostic_args(args), run_dir / "duty")
        radio = await _run_variant_cells(
            args, run_dir / "radio", ["baseline", "radio-idle", "radio-advertise"], "radio-sweep"
        )
        peripheral = await _run_variant_cells(
            args, run_dir / "peripheral", ["baseline", "peripherals"], "peripheral-sweep"
        )
        dcdc = await _run_variant_cells(
            _diagnostic_args(args), run_dir / "dcdc", ["dcdc-off", "dcdc-on"], "dcdc-sweep"
        )
        return {
            "status": "completed",
            "phase_a": phase_a,
            "idle": idle,
            "duty": duty,
            "radio": radio,
            "peripheral": peripheral,
            "dcdc": dcdc,
        }
    raise AssertionError(args.phase)


def _selected_variants(args: argparse.Namespace, phase_variants: list[str]) -> list[str]:
    if args.variants is None:
        return phase_variants
    selected = [variant for variant in phase_variants if variant in args.variants]
    if not selected:
        raise ValueError(f"No selected variants apply to this phase: {args.variants}")
    return selected


def _diagnostic_args(args: argparse.Namespace) -> argparse.Namespace:
    clone = argparse.Namespace(**vars(args))
    clone.warmups = min(args.warmups, 1)
    clone.measured = min(args.measured, 5)
    return clone


async def _run_reproduction(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    cell = await _measure_variant_cell(args, run_dir, "baseline", "phase-a-reproduction")
    ina = cell["metrics"].get("ina219", {})
    fnb = cell["metrics"].get("fnb58", {})
    measured = _stat_value(ina, "wh_per_1000", "p50")
    relative_delta = None
    if measured is not None:
        relative_delta = (
            measured - CANONICAL_NANO_KWS_WH_PER_1000
        ) / CANONICAL_NANO_KWS_WH_PER_1000
    meter_delta = _meter_relative_delta(ina, fnb)
    phase_a_pass = (
        measured is not None
        and abs(relative_delta or 0.0) <= CANONICAL_NANO_KWS_VARIANCE_BAND
        and meter_delta is not None
        and abs(meter_delta) <= 0.15
    )
    return {
        "status": "completed" if phase_a_pass else "failed",
        "phase": "phase-a",
        "phase_a_pass": phase_a_pass,
        "canonical_wh_per_1000": CANONICAL_NANO_KWS_WH_PER_1000,
        "canonical_variance_band": CANONICAL_NANO_KWS_VARIANCE_BAND,
        "relative_delta_vs_canonical": relative_delta,
        "fnb58_vs_ina219_relative_delta": meter_delta,
        "cell": cell,
    }


async def _run_idle_floor(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    build = _prepare_variant("baseline", args)
    status = _open_and_status(args.port)
    busy = await _collect_window(
        args,
        lambda: _serial_idle(args.port, "IDLE_BUSY", args.idle_seconds),
        run_dir / "idle-busy-telemetry.json",
    )
    sleep = await _collect_window(
        args,
        lambda: _serial_idle(args.port, "IDLE_SLEEP", args.idle_seconds),
        run_dir / "idle-sleep-telemetry.json",
    )
    return {
        "status": "completed",
        "phase": "idle",
        "build": build,
        "status_start": status,
        "idle_seconds": args.idle_seconds,
        "busy": busy,
        "sleep": sleep,
    }


async def _run_duty_cycle(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    build = _prepare_variant("baseline", args)
    iterations = args.iterations or _probe_iterations(
        args.port, args.probe_iterations, args.measurement_s
    )
    status = _open_and_status(args.port)
    back_to_back = await _measure_sessions(
        args,
        run_dir,
        "baseline",
        "duty-back-to-back",
        iterations,
        lambda: _serial_run(args.port, iterations),
        status,
        build,
    )
    paced = await _measure_sessions(
        args,
        run_dir,
        "baseline",
        "duty-host-paced",
        iterations,
        lambda: _serial_run_host_paced(args.port, iterations, args.paced_delay_s),
        status,
        build,
    )
    return {
        "status": "completed",
        "phase": "duty",
        "iterations_per_session": iterations,
        "paced_delay_s": args.paced_delay_s,
        "back_to_back": back_to_back,
        "host_paced": paced,
    }


async def _run_variant_cells(
    args: argparse.Namespace, run_dir: Path, variants: list[str], phase: str
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    cells = []
    for variant in variants:
        cell = await _measure_variant_cell(args, run_dir / variant, variant, phase)
        cells.append(cell)
    return {"status": "completed", "phase": phase, "cells": cells}


async def _measure_variant_cell(
    args: argparse.Namespace, run_dir: Path, variant: str, phase: str
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    build = _prepare_variant(variant, args)
    iterations = args.iterations or _probe_iterations(
        args.port, args.probe_iterations, args.measurement_s
    )
    status = _open_and_status(args.port)
    return await _measure_sessions(
        args,
        run_dir,
        variant,
        phase,
        iterations,
        lambda: _serial_run(args.port, iterations),
        status,
        build,
    )


async def _measure_sessions(
    args: argparse.Namespace,
    run_dir: Path,
    variant: str,
    phase: str,
    iterations: int,
    serial_action: Callable[[], dict[str, Any]],
    status: dict[str, Any],
    build: dict[str, Any],
) -> dict[str, Any]:
    sessions = []
    total = args.warmups + args.measured
    for index in range(total):
        measured = index >= args.warmups
        session_id = f"{phase}-{variant}-{index + 1:02d}"
        telemetry_path = run_dir / f"{session_id}-telemetry.json"
        window = await _collect_window(args, serial_action, telemetry_path)
        session = {
            "session_id": session_id,
            "warmup": not measured,
            "serial": window["action_result"],
            "telemetry": window["metrics"],
            "telemetry_path": str(telemetry_path.relative_to(ROOT)),
        }
        sessions.append(session)
        print(
            json.dumps(
                {"session": session_id, "warmup": not measured, "metrics": window["metrics"]},
                sort_keys=True,
            ),
            flush=True,
        )
    measured_sessions = [session for session in sessions if not session["warmup"]]
    metrics = _summarize_sessions(measured_sessions)
    cell = {
        "variant": variant,
        "variant_description": VARIANTS[variant].description,
        "phase": phase,
        "iterations_per_session": iterations,
        "warmups": args.warmups,
        "measured_sessions": args.measured,
        "status_start": status,
        "build": build,
        "sessions": sessions,
        "metrics": metrics,
    }
    (run_dir / f"{phase}-{variant}-summary.json").write_text(
        json.dumps(cell, indent=2, sort_keys=True), encoding="utf-8"
    )
    return cell


async def _collect_window(
    args: argparse.Namespace,
    action: Callable[[], dict[str, Any]],
    telemetry_path: Path,
) -> dict[str, Any]:
    sources = _telemetry_sources(args)
    samples: list[TelemetrySample] = []
    errors: list[str] = []
    stop_event = asyncio.Event()

    async def pump(source: TelemetrySource) -> None:
        try:
            async for sample in source.samples():
                samples.append(sample)
                if stop_event.is_set():
                    break
        except Exception as exc:
            errors.append(f"{source.name}: {type(exc).__name__}: {exc}")

    started: list[TelemetrySource] = []
    for source in sources:
        try:
            await _start_source_with_retry(source)
            started.append(source)
        except Exception as exc:
            errors.append(f"{source.name}: {type(exc).__name__}: {exc}")
    if args.require_fnb58 and not any(source.name == "fnb58" for source in started):
        for source in started:
            await source.stop()
        raise RuntimeError("FNB58 was required but did not start")
    if not any(source.name == "ina219" for source in started):
        for source in started:
            await source.stop()
        raise RuntimeError("INA219 did not start")

    tasks = [asyncio.create_task(pump(source)) for source in started]
    await asyncio.sleep(1.0)
    try:
        action_result = await asyncio.to_thread(action)
    finally:
        await asyncio.sleep(1.0)
        stop_event.set()
        for source in reversed(started):
            try:
                await source.stop()
            except Exception as exc:
                errors.append(f"{source.name} stop: {type(exc).__name__}: {exc}")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    rows = [_sample_to_dict(sample) for sample in samples]
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_path.write_text(
        json.dumps({"samples": rows, "errors": errors}, indent=2, sort_keys=True), encoding="utf-8"
    )
    metrics = _telemetry_metrics(samples, action_result.get("inference_count", 0))
    return {"action_result": action_result, "metrics": metrics, "errors": errors}


async def _start_source_with_retry(source: TelemetrySource) -> None:
    attempts = 4 if source.name == "fnb58" else 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            await source.start()
            return
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(2.0)
    if last_error is not None:
        raise last_error


def _telemetry_sources(args: argparse.Namespace) -> list[TelemetrySource]:
    return [
        Ina219Source(Ina219Config(address=0x40)),
        Bme280Source(Bme280Config(address=0x77)),
        FnirsiSource(FnirsiSourceConfig(address=args.fnb58_address)),
    ]


def _sample_to_dict(sample: TelemetrySample) -> dict[str, Any]:
    return {
        "timestamp": sample.timestamp.isoformat(),
        "source": sample.source_name,
        "values": sample.values,
        "unit_hints": sample.unit_hints,
    }


def _telemetry_metrics(samples: list[TelemetrySample], inference_count: int) -> dict[str, Any]:
    by_source: dict[str, list[TelemetrySample]] = {}
    for sample in samples:
        by_source.setdefault(sample.source_name, []).append(sample)
    return {
        source: _source_metrics(source_samples, inference_count)
        for source, source_samples in sorted(by_source.items())
    }


def _source_metrics(samples: list[TelemetrySample], inference_count: int) -> dict[str, Any]:
    powers = [
        (sample.timestamp, sample.values["power"]) for sample in samples if "power" in sample.values
    ]
    voltages = [sample.values["voltage"] for sample in samples if "voltage" in sample.values]
    currents = [sample.values["current"] for sample in samples if "current" in sample.values]
    joules = _integrate_joules(powers)
    wh = joules / 3600.0 if joules is not None else None
    wh_per_1000 = wh / inference_count * 1000.0 if wh is not None and inference_count > 0 else None
    duration_s = (powers[-1][0] - powers[0][0]).total_seconds() if len(powers) >= 2 else None
    avg_power_w = (
        joules / duration_s if joules is not None and duration_s and duration_s > 0 else None
    )
    return {
        "sample_count": len(samples),
        "power_sample_count": len(powers),
        "duration_s": duration_s,
        "joules": joules,
        "wh": wh,
        "wh_per_1000": wh_per_1000,
        "avg_power_w": avg_power_w,
        "avg_power_mw": avg_power_w * 1000.0 if avg_power_w is not None else None,
        "voltage_mean_v": statistics.fmean(voltages) if voltages else None,
        "current_mean_a": statistics.fmean(currents) if currents else None,
    }


def _integrate_joules(powers: list[tuple[dt.datetime, float]]) -> float | None:
    if len(powers) < 2:
        return None
    total = 0.0
    for previous, current in pairwise(powers):
        dt_s = (current[0] - previous[0]).total_seconds()
        if dt_s > 0:
            total += ((previous[1] + current[1]) / 2.0) * dt_s
    return total


def _summarize_sessions(sessions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_source: dict[str, dict[str, list[float]]] = {}
    for session in sessions:
        for source, metrics in session["telemetry"].items():
            bucket = by_source.setdefault(source, {})
            for key in ("wh_per_1000", "avg_power_mw", "joules"):
                value = metrics.get(key)
                if value is not None and math.isfinite(value):
                    bucket.setdefault(key, []).append(float(value))
    return {
        source: {key: _stats(values) for key, values in metrics.items()}
        for source, metrics in by_source.items()
    }


def _stats(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "p50": statistics.median(values),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _meter_relative_delta(ina: dict[str, Any], fnb: dict[str, Any]) -> float | None:
    ina_p50 = _stat_value(ina, "wh_per_1000", "p50")
    fnb_p50 = _stat_value(fnb, "wh_per_1000", "p50")
    if ina_p50 is None or fnb_p50 is None or ina_p50 == 0:
        return None
    return (fnb_p50 - ina_p50) / ina_p50


def _stat_value(source_metrics: dict[str, Any], key: str, stat: str) -> float | None:
    value = source_metrics.get(key)
    if isinstance(value, dict):
        resolved = value.get(stat)
        return float(resolved) if resolved is not None else None
    if value is None:
        return None
    return float(value)


def _prepare_variant(variant_name: str, args: argparse.Namespace) -> dict[str, Any]:
    build = _build_variant(variant_name, args)
    if not build["build"]["ok"]:
        raise RuntimeError(f"Build failed for {variant_name}: {build['build']['tail']}")
    if not args.skip_upload:
        upload = _upload_variant(Path(build["project_dir"]), build["env"], args.port)
        build["upload"] = upload
        if not upload["ok"]:
            raise RuntimeError(f"Upload failed for {variant_name}: {upload['tail']}")
        time.sleep(3.0)
    return build


def _build_variant(variant_name: str, args: argparse.Namespace) -> dict[str, Any]:
    variant = VARIANTS[variant_name]
    target = P3.TARGET_CONFIGS["nano33"]
    project_dir = _stage_variant_project(target, variant, args)
    build = P3._build_firmware(project_dir, target.platformio_env)
    build["tail"] = _last_lines(build["output"])
    return {
        "variant": variant_name,
        "description": variant.description,
        "project_dir": str(project_dir),
        "env": target.platformio_env,
        "build": build,
    }


def _stage_variant_project(target: Any, variant: Variant, args: argparse.Namespace) -> Path:
    project_dir = BUILD_ROOT / variant.name
    src_dir = project_dir / "src"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    src_dir.mkdir(parents=True)
    ini = _platformio_ini(target, variant, args.port)
    (project_dir / "platformio.ini").write_text(ini, encoding="utf-8")
    (src_dir / "main.cpp").write_text(_variant_cpp(), encoding="utf-8")
    (src_dir / "model_data.cc").write_text(P3._model_source("kws"), encoding="utf-8")
    (src_dir / "model_data.h").write_text(P3._model_header(), encoding="utf-8")
    (src_dir / "input_data.h").write_text(
        P3._input_header("kws", args.sample_count), encoding="utf-8"
    )
    return project_dir


def _platformio_ini(target: Any, variant: Variant, port: str) -> str:
    text = target.platformio_ini.format(serial_port=port, version=__version__)
    if variant.build_flags:
        text = text.replace(
            f'build_flags = -w -Wno-cpp -DSIGNAL_BENCH_VERSION=\\"{__version__}\\"',
            f'build_flags = -w -Wno-cpp -DSIGNAL_BENCH_VERSION=\\"{__version__}\\" '
            + " ".join(variant.build_flags),
        )
    if variant.lib_deps:
        insertion = "\n".join(f"    {dep}" for dep in variant.lib_deps)
        text = text.rstrip() + "\n" + insertion + "\n"
    return text


def _variant_cpp() -> str:
    cpp = P3.CPP_TEMPLATE
    cpp = cpp.replace(
        '#include "model_data.h"\n',
        '#include "model_data.h"\n' + NANO33_ENERGY_INCLUDE_INJECTION + "\n",
    )
    cpp = cpp.replace(
        'static const char *init_error = "not initialized";\n',
        'static const char *init_error = "not initialized";\n' + NANO33_ENERGY_SUPPORT_INJECTION + "\n",
    )
    cpp = cpp.replace(
        "  init_model();\n}",
        "  nano33_energy_configure_power();\n  nano33_energy_init_ble();\n  nano33_energy_init_peripherals();\n  init_model();\n}",
    )
    cpp = cpp.replace(
        "  if (!SIGNAL_BENCH_SERIAL.available()) {\n    delay(1);\n    return;\n  }\n",
        "  nano33_energy_poll();\n  if (!SIGNAL_BENCH_SERIAL.available()) {\n    delay(1);\n    return;\n  }\n",
    )
    cpp = cpp.replace(
        "  const char *payload = nullptr;\n",
        '  const char *payload = nullptr;\n  float nano33_energy_seconds = 0.0f;\n  if (line == "STATUS") {\n    nano33_energy_emit_status();\n    return;\n  }\n  if (nano33_energy_parse_seconds_command(line.c_str(), "IDLE_BUSY", &nano33_energy_seconds)) {\n    nano33_energy_idle_busy(nano33_energy_seconds);\n    return;\n  }\n  if (nano33_energy_parse_seconds_command(line.c_str(), "IDLE_SLEEP", &nano33_energy_seconds)) {\n    nano33_energy_idle_sleep(nano33_energy_seconds);\n    return;\n  }\n',
    )
    cpp = cpp.replace(
        '  emit_err("EINVAL", "expected RUN <task_id> <iterations> or EVAL <task_id> <sample_index> <base64-int8-input>");',
        '  emit_err("EINVAL", "expected STATUS, IDLE_BUSY <seconds>, IDLE_SLEEP <seconds>, RUN <task_id> <iterations>, or EVAL <task_id> <sample_index> <base64-int8-input>");',
    )
    return cpp


def _upload_variant(project_dir: Path, env: str, port: str) -> dict[str, Any]:
    process = subprocess.run(
        ["pio", "run", "-d", str(project_dir), "-e", env, "-t", "upload", "--upload-port", port],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "output": process.stdout,
        "tail": _last_lines(process.stdout),
    }


def _probe_iterations(port: str, probe_iterations: int, measurement_s: float) -> int:
    result = _serial_run(port, probe_iterations)
    durations_s = [duration / 1_000_000.0 for duration in result["durations_us"] if duration > 0]
    if not durations_s:
        raise RuntimeError("Probe did not produce durations")
    mean_s = statistics.fmean(durations_s)
    return max(1, min(5000, math.ceil(measurement_s / mean_s)))


def _open_and_status(port: str) -> dict[str, Any]:
    with serial.Serial(port, 115200, timeout=5, write_timeout=5) as handle:
        time.sleep(1.0)
        _drain(handle)
        handle.write(b"STATUS\n")
        handle.flush()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            line = handle.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if line.startswith("STATUS_JSON "):
                return json.loads(line.removeprefix("STATUS_JSON "))
            if line.startswith("ERR "):
                raise RuntimeError(line)
    raise TimeoutError("No STATUS_JSON from Nano 33")


def _serial_idle(port: str, command: str, seconds: float) -> dict[str, Any]:
    with serial.Serial(port, 115200, timeout=max(5.0, seconds + 10.0), write_timeout=5) as handle:
        time.sleep(1.0)
        _drain(handle)
        handle.write(f"{command} {seconds:.3f}\n".encode())
        handle.flush()
        deadline = time.monotonic() + seconds + 20.0
        while time.monotonic() < deadline:
            line = handle.readline().decode("utf-8", errors="replace").strip()
            if line.startswith("IDLE_DONE"):
                return {"mode": command, "seconds": seconds, "line": line, "inference_count": 0}
            if line.startswith("ERR "):
                raise RuntimeError(line)
    raise TimeoutError(f"No IDLE_DONE for {command}")


def _serial_run(port: str, iterations: int) -> dict[str, Any]:
    with serial.Serial(port, 115200, timeout=10, write_timeout=5) as handle:
        time.sleep(1.0)
        _drain(handle)
        handle.write(f"RUN kws {iterations}\n".encode())
        handle.flush()
        return _read_run(handle, iterations)


def _serial_run_host_paced(port: str, iterations: int, delay_s: float) -> dict[str, Any]:
    all_durations: list[int] = []
    all_results: list[dict[str, Any]] = []
    with serial.Serial(port, 115200, timeout=10, write_timeout=5) as handle:
        time.sleep(1.0)
        _drain(handle)
        for index in range(iterations):
            handle.write(b"RUN kws 1\n")
            handle.flush()
            result = _read_run(handle, 1)
            all_durations.extend(result["durations_us"])
            all_results.extend(result["results"])
            if index + 1 < iterations and delay_s > 0:
                time.sleep(delay_s)
    return {
        "mode": "host-paced",
        "iterations_requested": iterations,
        "inference_count": len(all_durations),
        "durations_us": all_durations,
        "results": all_results,
    }


def _read_run(handle: serial.Serial, iterations: int) -> dict[str, Any]:
    durations: list[int] = []
    results: list[dict[str, Any]] = []
    deadline = time.monotonic() + max(30.0, iterations * 2.0)
    while time.monotonic() < deadline:
        line = handle.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if line.startswith("RESULT "):
            parts = line.split(" ", 3)
            if len(parts) == 4:
                durations.append(int(parts[2]))
                try:
                    payload = json.loads(parts[3])
                except json.JSONDecodeError:
                    payload = {"raw": parts[3]}
                results.append(payload)
        elif line.startswith("DONE "):
            return {
                "mode": "back-to-back",
                "iterations_requested": iterations,
                "done_line": line,
                "inference_count": len(durations),
                "durations_us": durations,
                "duration_us_p50": statistics.median(durations) if durations else None,
                "results": results,
            }
        elif line.startswith("ERR "):
            raise RuntimeError(line)
    raise TimeoutError(f"No DONE after RUN kws {iterations}")


def _drain(handle: serial.Serial) -> None:
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        if handle.in_waiting:
            handle.read(handle.in_waiting)
        time.sleep(0.02)


def _last_lines(text: str, count: int = 25) -> str:
    return "\n".join(text.splitlines()[-count:])


def _write_report(run_dir: Path, result: dict[str, Any]) -> None:
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    lines = [
        "# Nano 33 energy investigation Nano 33 Energy Investigation",
        "",
        f"Generated: {dt.datetime.now(dt.UTC).isoformat()}",
        "",
        f"Status: **{result.get('status', 'completed')}**",
        "",
        "All artifacts in this directory are Nano 33 energy investigation investigation artifacts and do not replace Post 1 Tier 1 data.",
        "",
    ]
    lines.extend(_markdown_for_result(result))
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _markdown_for_result(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if result.get("phase") == "phase-a":
        lines.extend(
            [
                "## Phase A Reproduction",
                "",
                f"- Phase A pass: `{result['phase_a_pass']}`",
                f"- INA219 vs canonical relative delta: `{result['relative_delta_vs_canonical']}`",
                f"- FNB58 vs INA219 relative delta: `{result['fnb58_vs_ina219_relative_delta']}`",
                "",
            ],
        )
    if "cells" in result:
        lines.extend(
            [
                "## Cells",
                "",
                "| Variant | INA219 Wh/1000 p50 | FNB58 Wh/1000 p50 | INA219 avg mW p50 |",
                "|---|---:|---:|---:|",
            ]
        )
        for cell in result["cells"]:
            lines.append(_cell_row(cell))
        lines.append("")
    if "cell" in result:
        lines.extend(
            [
                "## Cell",
                "",
                "| Variant | INA219 Wh/1000 p50 | FNB58 Wh/1000 p50 | INA219 avg mW p50 |",
                "|---|---:|---:|---:|",
                _cell_row(result["cell"]),
                "",
            ]
        )
    return lines


def _cell_row(cell: dict[str, Any]) -> str:
    metrics = cell.get("metrics", {})
    ina = metrics.get("ina219", {})
    fnb = metrics.get("fnb58", {})
    return "| {variant} | {ina_wh} | {fnb_wh} | {ina_mw} |".format(
        variant=cell.get("variant", ""),
        ina_wh=_stat_p50(ina, "wh_per_1000"),
        fnb_wh=_stat_p50(fnb, "wh_per_1000"),
        ina_mw=_stat_p50(ina, "avg_power_mw"),
    )


def _stat_p50(source_metrics: dict[str, Any], key: str) -> str:
    value = (source_metrics.get(key) or {}).get("p50")
    return "" if value is None else f"{value:.9g}"


if __name__ == "__main__":
    raise SystemExit(main())
