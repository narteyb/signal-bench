# SPDX-License-Identifier: Apache-2.0
"""Run the P3 MCU benchmark matrix with telemetry capture.

This script is intentionally hardware-facing and is not part of the normal
mock CI path. It stages one PlatformIO firmware project per (target, task)
cell from the N3 variant TFLite artifacts and MCU subset inputs, flashes the
device through ``CommandMCUAdapter``, captures telemetry with the async source
contract, and persists rows through the existing signal-bench schema.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.adapters.exceptions import MeasureError, PrepareError
from signal_bench.adapters.mcu import CommandMCUAdapter, MCUAdapterConfig
from signal_bench.artifacts import ArtifactUnavailableError, ensure_artifact
from signal_bench.ids import new_id
from signal_bench.schema import Failure, Result, Run, Target, Task, TelemetrySample
from signal_bench.tasks import get_task
from signal_bench.telemetry.orchestrator import TelemetryOrchestrator
from signal_bench.telemetry.sources.bme280 import Bme280Config, Bme280Source
from signal_bench.telemetry.sources.fnirsi import FnirsiSource, FnirsiSourceConfig
from signal_bench.telemetry.sources.ina219 import Ina219Config, Ina219Source

if TYPE_CHECKING:
    from signal_bench.adapters import InferenceResult, TaskSpec
    from signal_bench.telemetry.base import TelemetrySource

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "p3-mcu"
MANIFEST_PATH = ROOT / "models" / "reference" / "manifest.yaml"
INVENTORY_PATH = ROOT / "reports" / "p3_mcu_inventory.md"
VARIANT_ROOT = Path("<local-path>")
FNB58_ADDRESS = "<fnb58-address>"
SERIAL_PORT_PLACEHOLDER = "<serial-port>"
TASKS = ("kws", "ic", "ad")
TARGETS = ("esp32s3", "nano33", "f401re")
VARIANT_DIRS = {
    "kws": VARIANT_ROOT / "kws-qat-int8" / "artifacts",
    "ic": VARIANT_ROOT / "ic-resnet-prune-40" / "artifacts",
    "ad": VARIANT_ROOT / "ad-distill-50" / "artifacts",
}
LINEAGE_PATHS = {task_name: path / "lineage.json" for task_name, path in VARIANT_DIRS.items()}
INPUT_ELEMENTS = {"kws": 49 * 10, "ic": 32 * 32 * 3, "ad": 640}
OUTPUT_ELEMENTS = {"kws": 12, "ic": 10, "ad": 640}
ARENA_BYTES = {"kws": 48 * 1024, "ic": 64 * 1024, "ad": 24 * 1024}
REGENERATE_SUBSET_COMMANDS = {
    "ic": "uv run python scripts/datasets/prepare_ic.py",
    "ad": (
        "uv run python scripts/datasets/stage_dcase.py && "
        "uv run python scripts/datasets/prepare_ad.py"
    ),
}
BYTES_PER_LINE = 12


@dataclass(frozen=True, slots=True)
class TargetConfig:
    """Hardware and PlatformIO settings for one MCU target."""

    name: str
    platformio_env: str
    platformio_ini: str
    serial_port: str
    ram_bytes: int
    flash_bytes: int
    post_flash_delay_s: float = 0.0


TARGET_CONFIGS = {
    "esp32s3": TargetConfig(
        name="esp32s3",
        platformio_env="esp32-s3-devkitc-1",
        serial_port=SERIAL_PORT_PLACEHOLDER,
        ram_bytes=327_680,
        flash_bytes=1_048_576,
        platformio_ini="""[env:esp32-s3-devkitc-1]
platform = espressif32@6.6.0
board = esp32-s3-devkitc-1
framework = arduino
monitor_speed = 115200
upload_port = {serial_port}
monitor_port = {serial_port}
build_flags = -w -DSIGNAL_BENCH_VERSION=\\\"{version}\\\"
lib_deps =
    spaziochirale/Chirale_TensorFLowLite@2.0.0
""",
    ),
    "nano33": TargetConfig(
        name="nano33",
        platformio_env="nano33ble",
        serial_port=SERIAL_PORT_PLACEHOLDER,
        ram_bytes=262_144,
        flash_bytes=983_040,
        post_flash_delay_s=3.0,
        platformio_ini="""[env:nano33ble]
platform = nordicnrf52@10.11.0
board = nano33ble
framework = arduino
monitor_speed = 115200
upload_port = {serial_port}
monitor_port = {serial_port}
build_flags = -w -Wno-cpp -DSIGNAL_BENCH_VERSION=\\\"{version}\\\"
lib_deps =
    spaziochirale/Chirale_TensorFLowLite@2.0.0
""",
    ),
    "f401re": TargetConfig(
        name="f401re",
        platformio_env="nucleo_f401re",
        serial_port=SERIAL_PORT_PLACEHOLDER,
        ram_bytes=98_304,
        flash_bytes=524_288,
        platformio_ini="""[env:nucleo_f401re]
platform = ststm32@19.6.0
board = nucleo_f401re
framework = arduino
monitor_speed = 115200
upload_port = {serial_port}
monitor_port = {serial_port}
build_unflags =
    -std=gnu++11
    -std=gnu++14
build_flags = -w -std=gnu++17 -DSIGNAL_BENCH_VERSION=\\\"{version}\\\"
lib_compat_mode = off
lib_deps =
    spaziochirale/Chirale_TensorFLowLite@2.0.0
""",
    ),
}


CPP_TEMPLATE = r"""
#include <Arduino.h>
#include <Chirale_TensorFlowLite.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/schema/schema_generated.h>

#include <stdlib.h>

#include "input_data.h"
#include "model_data.h"

#ifndef SIGNAL_BENCH_VERSION
#define SIGNAL_BENCH_VERSION "unknown"
#endif

#ifdef SIGNAL_BENCH_USE_USART1_PA9_PA10
static HardwareSerial BenchSerial(PA10, PA9);
#define SIGNAL_BENCH_SERIAL BenchSerial
#else
#define SIGNAL_BENCH_SERIAL Serial
#endif

alignas(16) static uint8_t tensor_arena[kTensorArenaBytes];
alignas(16) static int8_t eval_input_buffer[kInputElements];
static tflite::MicroMutableOpResolver<8> resolver;
static const tflite::Model *model = nullptr;
static tflite::MicroInterpreter *interpreter = nullptr;
static TfLiteTensor *input_tensor = nullptr;
static TfLiteTensor *output_tensor = nullptr;
static bool init_ok = false;
static const char *init_error = "not initialized";

static bool parse_run(const char *line, char *task_id, size_t task_id_len, int *iterations) {
  while (*line == ' ' || *line == '\t') {
    line++;
  }
  if (strncmp(line, "RUN", 3) != 0 || (line[3] != ' ' && line[3] != '\t')) {
    return false;
  }
  char parsed_task[24] = {0};
  int parsed_iterations = 0;
  if (sscanf(line + 3, "%23s %d", parsed_task, &parsed_iterations) != 2) {
    return false;
  }
  if (parsed_iterations <= 0) {
    return false;
  }
  strncpy(task_id, parsed_task, task_id_len - 1);
  *iterations = parsed_iterations;
  return true;
}

static bool parse_eval(
    const char *line,
    char *task_id,
    size_t task_id_len,
    int *sample_index,
    const char **payload) {
  while (*line == ' ' || *line == '\t') {
    line++;
  }
  if (strncmp(line, "EVAL", 4) != 0 || (line[4] != ' ' && line[4] != '\t')) {
    return false;
  }
  const char *cursor = line + 4;
  while (*cursor == ' ' || *cursor == '\t') {
    cursor++;
  }
  size_t task_len = 0;
  while (cursor[task_len] != '\0' && cursor[task_len] != ' ' && cursor[task_len] != '\t') {
    task_len++;
  }
  if (task_len == 0 || task_len >= task_id_len) {
    return false;
  }
  memcpy(task_id, cursor, task_len);
  task_id[task_len] = '\0';
  cursor += task_len;
  while (*cursor == ' ' || *cursor == '\t') {
    cursor++;
  }
  char *endptr = nullptr;
  long parsed_index = strtol(cursor, &endptr, 10);
  if (endptr == cursor || parsed_index < 0) {
    return false;
  }
  cursor = endptr;
  while (*cursor == ' ' || *cursor == '\t') {
    cursor++;
  }
  if (*cursor == '\0') {
    return false;
  }
  *sample_index = static_cast<int>(parsed_index);
  *payload = cursor;
  return true;
}

static int base64_value(char value) {
  if (value >= 'A' && value <= 'Z') {
    return value - 'A';
  }
  if (value >= 'a' && value <= 'z') {
    return value - 'a' + 26;
  }
  if (value >= '0' && value <= '9') {
    return value - '0' + 52;
  }
  if (value == '+') {
    return 62;
  }
  if (value == '/') {
    return 63;
  }
  return -1;
}

static int decode_base64_int8(const char *payload, int8_t *output, int output_capacity) {
  int accumulator = 0;
  int bits = -8;
  int output_len = 0;
  for (const char *cursor = payload; *cursor != '\0'; cursor++) {
    const char ch = *cursor;
    if (ch == '\r' || ch == '\n' || ch == ' ' || ch == '\t') {
      break;
    }
    if (ch == '=') {
      break;
    }
    const int decoded = base64_value(ch);
    if (decoded < 0) {
      return -1;
    }
    accumulator = (accumulator << 6) | decoded;
    bits += 6;
    if (bits >= 0) {
      if (output_len >= output_capacity) {
        return -1;
      }
      output[output_len++] = static_cast<int8_t>((accumulator >> bits) & 0xff);
      bits -= 8;
    }
  }
  return output_len;
}

static void emit_err(const char *code, const char *message) {
  SIGNAL_BENCH_SERIAL.print("ERR ");
  SIGNAL_BENCH_SERIAL.print(code);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.println(message);
}

static void emit_done(int iterations) {
  SIGNAL_BENCH_SERIAL.print("DONE ");
  SIGNAL_BENCH_SERIAL.println(iterations);
}

static int argmax_int8(const int8_t *values, int count) {
  int best_index = 0;
  int8_t best_value = values[0];
  for (int i = 1; i < count; i++) {
    if (values[i] > best_value) {
      best_value = values[i];
      best_index = i;
    }
  }
  return best_index;
}

static float ad_mse(const int8_t *input_values, const int8_t *output_values) {
  float total = 0.0f;
  for (int i = 0; i < kOutputElements; i++) {
    const float in_value = (static_cast<int>(input_values[i]) - kInputZeroPoint) * kInputScale;
    const float out_value = (static_cast<int>(output_values[i]) - kOutputZeroPoint) * kOutputScale;
    const float diff = in_value - out_value;
    total += diff * diff;
  }
  return total / static_cast<float>(kOutputElements);
}

static void emit_result(int iter_id, uint32_t duration_us, int sample_index) {
  SIGNAL_BENCH_SERIAL.print("RESULT ");
  SIGNAL_BENCH_SERIAL.print(iter_id);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.print(duration_us);
  SIGNAL_BENCH_SERIAL.print(" ");
  if (strcmp(kTaskId, "ad") == 0) {
    const float score = ad_mse(&kInputs[sample_index * kInputElements], output_tensor->data.int8);
    SIGNAL_BENCH_SERIAL.print("{\"sample\":");
    SIGNAL_BENCH_SERIAL.print(sample_index);
    SIGNAL_BENCH_SERIAL.print(",\"label\":");
    SIGNAL_BENCH_SERIAL.print(kLabels[sample_index]);
    SIGNAL_BENCH_SERIAL.print(",\"score\":");
    SIGNAL_BENCH_SERIAL.print(score, 6);
    SIGNAL_BENCH_SERIAL.print(",\"arena_used\":");
    SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(interpreter->arena_used_bytes()));
    SIGNAL_BENCH_SERIAL.println("}");
  } else {
    const int pred = argmax_int8(output_tensor->data.int8, kOutputElements);
    SIGNAL_BENCH_SERIAL.print("{\"sample\":");
    SIGNAL_BENCH_SERIAL.print(sample_index);
    SIGNAL_BENCH_SERIAL.print(",\"label\":");
    SIGNAL_BENCH_SERIAL.print(kLabels[sample_index]);
    SIGNAL_BENCH_SERIAL.print(",\"pred\":");
    SIGNAL_BENCH_SERIAL.print(pred);
    SIGNAL_BENCH_SERIAL.print(",\"correct\":");
    SIGNAL_BENCH_SERIAL.print(pred == kLabels[sample_index] ? "true" : "false");
    SIGNAL_BENCH_SERIAL.print(",\"arena_used\":");
    SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(interpreter->arena_used_bytes()));
    SIGNAL_BENCH_SERIAL.println("}");
  }
}

static void run_task(const char *task_id, int iterations) {
  if (strcmp(task_id, kTaskId) != 0) {
    emit_err("EINVAL", "firmware task mismatch");
    return;
  }
  if (!init_ok) {
    emit_err("EHW", init_error);
    emit_err("EHW", init_error);
    emit_err("EHW", init_error);
    return;
  }
  if (input_tensor->bytes < kInputElements || output_tensor->bytes < kOutputElements) {
    emit_err("EINFER", "tensor byte count too small");
    return;
  }
  for (int iter = 0; iter < iterations; iter++) {
    const int sample_index = iter % kSampleCount;
    memcpy(input_tensor->data.int8, &kInputs[sample_index * kInputElements], kInputElements);
    const uint32_t t0 = micros();
    const TfLiteStatus status = interpreter->Invoke();
    const uint32_t elapsed = micros() - t0;
    if (status != kTfLiteOk) {
      emit_err("EINFER", "Invoke failed");
      continue;
    }
    emit_result(iter, elapsed, sample_index);
  }
  emit_done(iterations);
}

static void run_eval(const char *task_id, int sample_index, const char *payload) {
  if (strcmp(task_id, kTaskId) != 0) {
    emit_err("EINVAL", "firmware task mismatch");
    return;
  }
  if (strcmp(kTaskId, "kws") != 0 && strcmp(kTaskId, "ad") != 0) {
    emit_err("EINVAL", "EVAL supports kws and ad only");
    return;
  }
  if (!init_ok) {
    emit_err("EHW", init_error);
    return;
  }
  if (input_tensor->bytes < kInputElements || output_tensor->bytes < kOutputElements) {
    emit_err("EINFER", "tensor byte count too small");
    return;
  }
  const int decoded_len = decode_base64_int8(payload, eval_input_buffer, kInputElements);
  if (decoded_len != kInputElements) {
    emit_err("EBADLEN", "decoded tensor length mismatch");
    return;
  }
  memcpy(input_tensor->data.int8, eval_input_buffer, kInputElements);
  const uint32_t t0 = micros();
  const TfLiteStatus status = interpreter->Invoke();
  const uint32_t elapsed = micros() - t0;
  if (status != kTfLiteOk) {
    emit_err("EINFER", "Invoke failed");
    return;
  }
  if (strcmp(kTaskId, "ad") == 0) {
    const float score = ad_mse(eval_input_buffer, output_tensor->data.int8);
    SIGNAL_BENCH_SERIAL.print("SCORE ");
    SIGNAL_BENCH_SERIAL.print(sample_index);
    SIGNAL_BENCH_SERIAL.print(" ");
    SIGNAL_BENCH_SERIAL.print(elapsed);
    SIGNAL_BENCH_SERIAL.print(" ");
    SIGNAL_BENCH_SERIAL.println(score, 6);
    return;
  }
  const int pred = argmax_int8(output_tensor->data.int8, kOutputElements);
  SIGNAL_BENCH_SERIAL.print("PRED ");
  SIGNAL_BENCH_SERIAL.print(sample_index);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.print(elapsed);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.println(pred);
}

static void init_model() {
  if (strcmp(kTaskId, "kws") == 0) {
    resolver.AddAveragePool2D();
    resolver.AddConv2D();
    resolver.AddDepthwiseConv2D();
    resolver.AddFullyConnected();
    resolver.AddQuantize();
    resolver.AddReshape();
    resolver.AddSoftmax();
  } else if (strcmp(kTaskId, "ic") == 0) {
    resolver.AddAdd();
    resolver.AddAveragePool2D();
    resolver.AddConv2D();
    resolver.AddFullyConnected();
    resolver.AddReshape();
    resolver.AddSoftmax();
  } else if (strcmp(kTaskId, "ad") == 0) {
    resolver.AddFullyConnected();
  } else {
    init_error = "unknown task resolver";
    return;
  }
  model = tflite::GetModel(kModelData);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    init_error = "schema version mismatch";
    return;
  }
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, kTensorArenaBytes);
  interpreter = &static_interpreter;
  if (interpreter->AllocateTensors() != kTfLiteOk) {
    init_error = "AllocateTensors failed";
    return;
  }
  input_tensor = interpreter->input(0);
  output_tensor = interpreter->output(0);
  if (input_tensor == nullptr || output_tensor == nullptr) {
    init_error = "missing tensor";
    return;
  }
  init_ok = true;
  init_error = "";
}

void setup() {
  SIGNAL_BENCH_SERIAL.begin(115200);
  uint32_t start_ms = millis();
  while (!SIGNAL_BENCH_SERIAL && millis() - start_ms < 3000) {
    delay(10);
  }
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  init_model();
}

void loop() {
  if (!SIGNAL_BENCH_SERIAL.available()) {
    delay(1);
    return;
  }
  String line = SIGNAL_BENCH_SERIAL.readStringUntil('\n');
  char task_id[24] = {0};
  int iterations = 0;
  int sample_index = 0;
  const char *payload = nullptr;
  if (parse_run(line.c_str(), task_id, sizeof(task_id), &iterations)) {
    digitalWrite(LED_BUILTIN, LOW);
    run_task(task_id, iterations);
    digitalWrite(LED_BUILTIN, HIGH);
    return;
  }
  if (parse_eval(line.c_str(), task_id, sizeof(task_id), &sample_index, &payload)) {
    digitalWrite(LED_BUILTIN, LOW);
    run_eval(task_id, sample_index, payload);
    digitalWrite(LED_BUILTIN, HIGH);
    return;
  }
  emit_err(
      "EINVAL",
      "expected RUN <task_id> <iterations> or EVAL <task_id> <sample_index> <base64-int8-input>");
  return;
}
"""


def main() -> int:
    """Run the requested MCU matrix cells and append inventory entries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "p3_mcu_matrix.db")
    parser.add_argument("--targets", nargs="+", choices=TARGETS, default=list(TARGETS))
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--fnb58-address", default=FNB58_ADDRESS)
    parser.add_argument("--no-fnb58", action="store_true")
    parser.add_argument("--sample-count", type=int, default=12)
    parser.add_argument("--measurement-s", type=float, default=32.0)
    parser.add_argument("--probe-iterations", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=5000)
    parser.add_argument(
        "--port",
        action="append",
        default=[],
        metavar="TARGET=PORT",
        help="Set a target serial port from discovery, e.g. --port esp32s3=<discovered-port>.",
    )
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--session-label", help="Optional session label stored in run metadata.")
    parser.add_argument("--rerun-reason", help="Optional rerun reason stored in run metadata.")
    parser.add_argument(
        "--f401re-power-connector",
        help="F401RE topology: board power connector or rail used for the metered supply.",
    )
    parser.add_argument(
        "--f401re-jp5-position",
        help="F401RE topology: observed JP5 power-source position.",
    )
    parser.add_argument(
        "--f401re-usb-vbus-routing",
        help="F401RE topology: USB/VBUS routing and whether USB VBUS is metered or isolated.",
    )
    parser.add_argument(
        "--f401re-stlink-state",
        help="F401RE topology: observed ST-LINK USB/VCP enumeration state.",
    )
    parser.add_argument(
        "--f401re-topology-note",
        action="append",
        default=[],
        help="Additional F401RE topology note. May be passed more than once.",
    )
    args = parser.parse_args()

    _apply_port_overrides(args.port)
    _validate_topology_args(args)
    os.environ.setdefault("BLINKA_MCP2221", "1")
    os.environ.setdefault("SIGNAL_BENCH_REAL_I2C", "1")
    os.environ.setdefault("FNB58_TRANSPORT", "ble")
    _ensure_database(args.db)
    engine = create_engine(f"sqlite:///{args.db}")
    session_factory = sessionmaker(bind=engine)
    try:
        summaries: list[dict[str, Any]] = []
        for target_name in args.targets:
            for task_name in args.tasks:
                summary = asyncio.run(_run_cell(args, session_factory, target_name, task_name))
                summaries.append(summary)
                if not args.build_only:
                    _append_inventory(summary)
                print(json.dumps(summary, sort_keys=True))
        _print_matrix(summaries)
    finally:
        engine.dispose()
    return 0


def _apply_port_overrides(overrides: list[str]) -> None:
    for item in overrides:
        target_name, separator, serial_port = item.partition("=")
        if not separator or not target_name or not serial_port:
            raise SystemExit(f"invalid --port override {item!r}; expected TARGET=PORT")
        if target_name not in TARGET_CONFIGS:
            raise SystemExit(f"unknown --port target {target_name!r}; expected one of {TARGETS}")
        TARGET_CONFIGS[target_name] = replace(
            TARGET_CONFIGS[target_name],
            serial_port=serial_port,
        )


def _validate_topology_args(args: argparse.Namespace) -> None:
    if not args.build_only:
        missing_ports = [
            target_name
            for target_name in args.targets
            if TARGET_CONFIGS[target_name].serial_port == SERIAL_PORT_PLACEHOLDER
        ]
        if missing_ports:
            formatted = ", ".join(missing_ports)
            raise SystemExit(
                "Measurement runs require explicit serial ports from discovery: "
                f"{formatted}. Use scripts/discover_launch_tier_devices.py, then pass "
                "--port TARGET=PORT for each selected target.",
            )
    if args.build_only or "f401re" not in args.targets:
        return
    missing = [
        option
        for option in (
            "f401re_power_connector",
            "f401re_jp5_position",
            "f401re_usb_vbus_routing",
            "f401re_stlink_state",
        )
        if not getattr(args, option)
    ]
    if missing:
        formatted = ", ".join("--" + item.replace("_", "-") for item in missing)
        raise SystemExit(f"F401RE measurement runs require explicit topology: {formatted}")


def _f401re_topology_from_args(
    args: argparse.Namespace,
    target_config: TargetConfig,
) -> dict[str, Any] | None:
    if target_config.name != "f401re":
        return None
    return {
        "power_connector_used": args.f401re_power_connector,
        "jp5_position": args.f401re_jp5_position,
        "usb_vbus_routing": args.f401re_usb_vbus_routing,
        "stlink_enumeration_state": args.f401re_stlink_state,
        "topology_notes": list(args.f401re_topology_note),
    }


async def _run_cell(
    args: argparse.Namespace,
    session_factory: sessionmaker[Session],
    target_name: str,
    task_name: str,
) -> dict[str, Any]:
    target_config = TARGET_CONFIGS[target_name]
    task_spec = get_task(task_name)
    lineage = json.loads(LINEAGE_PATHS[task_name].read_text(encoding="utf-8"))
    target_row, task_row = _ensure_target_task(session_factory, target_config, task_spec)
    project_dir = _stage_firmware(target_config, task_name, sample_count=args.sample_count)
    build = _build_firmware(project_dir, target_config.platformio_env)
    if args.build_only:
        status = "build-pass" if build["ok"] else "build-fail"
        return _summary_base(target_name, task_name, status, lineage) | {
            "footprint": build["footprint"],
            "project_dir": str(project_dir),
            "error": None if build["ok"] else _last_lines(build["output"]),
        }
    if not build["ok"]:
        failure_mode = _classify_build_failure(build["output"])
        _write_failure(
            session_factory,
            target_row,
            task_row,
            task_name,
            failure_mode,
            build["output"],
            {"project_dir": str(project_dir), "footprint": build["footprint"], "lineage": lineage},
        )
        return _summary_base(target_name, task_name, "does-not-fit", lineage) | {
            "limiting_resource": failure_mode.replace("_memory_overflow", ""),
            "footprint": build["footprint"],
            "error": _last_lines(build["output"]),
        }

    adapter = _adapter_for_cell(target_config, project_dir, flash=not args.skip_upload)
    try:
        await adapter.prepare(new_id())
        probe_results = [
            result async for result in adapter.measure(task_spec, args.probe_iterations)
        ]
        probe_mean_us = statistics.fmean(
            result.duration_us for result in probe_results if result.error is None
        )
        estimated_iterations = math.ceil(args.measurement_s * 1_000_000 / probe_mean_us)
        iterations = max(1, min(args.max_iterations, estimated_iterations))
        await adapter.teardown()
    except (MeasureError, PrepareError, RuntimeError, ValueError, OSError) as exc:
        await adapter.teardown()
        _write_failure(
            session_factory,
            target_row,
            task_row,
            task_name,
            "toolchain_version_skew",
            str(exc),
            {"stage": "probe", "project_dir": str(project_dir), "lineage": lineage},
        )
        return _summary_base(target_name, task_name, "fail", lineage) | {"error": str(exc)}

    run_id = new_id()
    _create_run(
        session_factory,
        run_id,
        target_row,
        target_config,
        task_row,
        task_spec,
        iterations,
        lineage,
        build,
        project_dir,
        fnb58_enabled=not args.no_fnb58,
        session_label=args.session_label,
        rerun_reason=args.rerun_reason,
        topology=_f401re_topology_from_args(args, target_config),
    )
    telemetry = TelemetryOrchestrator(session_factory)
    adapter = _adapter_for_cell(target_config, project_dir, flash=False)
    results = []
    try:
        await adapter.prepare(run_id)
        await telemetry.start_run(run_id, _telemetry_sources(args))
        _mark_run_measurement_started(session_factory, run_id)
        results.extend([result async for result in adapter.measure(task_spec, iterations)])
    except (MeasureError, PrepareError) as exc:
        _mark_run_failed(session_factory, run_id, str(exc))
        raise
    finally:
        telemetry_state = await telemetry.stop_run()
        await adapter.teardown()

    _write_results(session_factory, run_id, results)
    _finish_run(session_factory, run_id, results)
    metrics = _cell_metrics(session_factory, run_id, results, lineage)
    status = "fail" if telemetry_state.partial else "pass"
    return _summary_base(target_name, task_name, status, lineage) | {
        "run_id": run_id,
        "iterations": iterations,
        "latency": metrics["latency"],
        "accuracy_proxy": metrics["accuracy_proxy"],
        "wh_per_1000_inferences": metrics["wh_per_1000_inferences"],
        "telemetry": metrics["telemetry"],
        "telemetry_partial": telemetry_state.partial,
        "telemetry_partial_sources": telemetry_state.failed_sources,
        "footprint": build["footprint"],
        "project_dir": str(project_dir),
    }


def _stage_firmware(target: TargetConfig, task_name: str, *, sample_count: int) -> Path:
    project_dir = BUILD_ROOT / f"{target.name}-{task_name}"
    src_dir = project_dir / "src"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    src_dir.mkdir(parents=True)
    (project_dir / "platformio.ini").write_text(
        target.platformio_ini.format(serial_port=target.serial_port, version=__version__),
        encoding="utf-8",
    )
    (src_dir / "main.cpp").write_text(CPP_TEMPLATE, encoding="utf-8")
    (src_dir / "model_data.cc").write_text(_model_source(task_name), encoding="utf-8")
    (src_dir / "model_data.h").write_text(_model_header(), encoding="utf-8")
    (src_dir / "input_data.h").write_text(_input_header(task_name, sample_count), encoding="utf-8")
    return project_dir


def _model_header() -> str:
    return """#pragma once
#include <cstdint>
extern const unsigned char kModelData[];
extern const unsigned int kModelDataLen;
"""


def _model_source(task_name: str) -> str:
    model_bytes = _variant_model_path(task_name).read_bytes()
    rows = []
    for offset in range(0, len(model_bytes), BYTES_PER_LINE):
        chunk = model_bytes[offset : offset + BYTES_PER_LINE]
        rows.append("  " + ", ".join(f"0x{value:02x}" for value in chunk) + ",")
    return (
        '#include "model_data.h"\n\n'
        "alignas(8) const unsigned char kModelData[] = {\n" + "\n".join(rows) + "\n};\n"
        f"const unsigned int kModelDataLen = {len(model_bytes)};\n"
    )


def _input_header(task_name: str, sample_count: int) -> str:
    inputs, labels = _selected_quantized_inputs(task_name, sample_count)
    flat = ", ".join(str(int(value)) for value in inputs.reshape(-1))
    label_text = ", ".join(str(int(value)) for value in labels)
    input_scale, input_zero, output_scale, output_zero = _variant_quantization(task_name)
    return f"""#pragma once
#include <cstdint>
static const char *const kTaskId = "{task_name}";
static constexpr int kSampleCount = {len(labels)};
static constexpr int kInputElements = {INPUT_ELEMENTS[task_name]};
static constexpr int kOutputElements = {OUTPUT_ELEMENTS[task_name]};
static constexpr int kTensorArenaBytes = {ARENA_BYTES[task_name]};
static constexpr float kInputScale = {_cpp_float(input_scale)};
static constexpr int kInputZeroPoint = {input_zero};
static constexpr float kOutputScale = {_cpp_float(output_scale)};
static constexpr int kOutputZeroPoint = {output_zero};
alignas(16) static const int8_t kInputs[kSampleCount * kInputElements] = {{{flat}}};
static const int8_t kLabels[kSampleCount] = {{{label_text}}};
"""


def _selected_quantized_inputs(task_name: str, sample_count: int) -> tuple[np.ndarray, np.ndarray]:
    subset_path = ROOT / "data" / "mcu_subsets" / task_name / "subset_v1.npz"
    if not subset_path.exists():
        try:
            subset_path = ensure_artifact(subset_path)
        except ArtifactUnavailableError:
            if task_name in REGENERATE_SUBSET_COMMANDS:
                command = REGENERATE_SUBSET_COMMANDS[task_name]
                msg = (
                    f"missing regenerated {task_name.upper()} subset: {subset_path}. "
                    f"Run `{command}` from the repo root first."
                )
                raise FileNotFoundError(msg) from None
            raise
    data = np.load(subset_path, allow_pickle=False)
    raw_inputs = data["inputs"]
    labels = data["labels"].astype(np.int16)
    selected = _balanced_indices(labels, sample_count)
    inputs = raw_inputs[selected]
    selected_labels = labels[selected].astype(np.int8)
    scale, zero_point, _output_scale, _output_zero = _variant_quantization(task_name)
    quantized = np.rint(inputs.astype(np.float32) / scale + zero_point)
    quantized = np.clip(quantized, -128, 127).astype(np.int8)
    return quantized.reshape(len(selected), -1), selected_labels


def _variant_model_path(task_name: str) -> Path:
    return VARIANT_DIRS[task_name] / "model.tflite"


def _variant_model_sha256(task_name: str) -> str:
    return hashlib.sha256(_variant_model_path(task_name).read_bytes()).hexdigest()


def _variant_quantization(task_name: str) -> tuple[float, int, float, int]:
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ModuleNotFoundError:
        from tensorflow.lite.python.interpreter import Interpreter  # type: ignore[no-redef]

    interpreter = Interpreter(model_path=str(_variant_model_path(task_name)))
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    input_scale, input_zero = input_details["quantization"]
    output_scale, output_zero = output_details["quantization"]
    return float(input_scale), int(input_zero), float(output_scale), int(output_zero)


def _cpp_float(value: float) -> str:
    text = f"{value:.12g}"
    if "e" not in text and "." not in text:
        text = f"{text}.0"
    return f"{text}f"


def _balanced_indices(labels: np.ndarray, sample_count: int) -> list[int]:
    by_label: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        by_label.setdefault(int(label), []).append(index)
    selected: list[int] = []
    while len(selected) < min(sample_count, len(labels)):
        progressed = False
        for label in sorted(by_label):
            bucket = by_label[label]
            offset = sum(1 for chosen in selected if int(labels[chosen]) == label)
            if offset < len(bucket):
                selected.append(bucket[offset])
                progressed = True
                if len(selected) >= sample_count:
                    break
        if not progressed:
            break
    return selected


def _build_firmware(project_dir: Path, env: str) -> dict[str, Any]:
    process = subprocess.run(
        ["pio", "run", "-d", str(project_dir), "-e", env],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = process.stdout
    return {
        "ok": process.returncode == 0,
        "output": output,
        "footprint": _parse_footprint(project_dir, env, output),
    }


def _parse_footprint(project_dir: Path, env: str, output: str) -> dict[str, Any]:
    build_dir = project_dir / ".pio" / "build" / env
    footprint: dict[str, Any] = {
        "firmware_bin_bytes": _size_or_none(build_dir / "firmware.bin"),
        "firmware_elf_bytes": _size_or_none(build_dir / "firmware.elf"),
    }
    ram_match = re.search(r"RAM:\s+.*used\s+(\d+) bytes from (\d+) bytes", output)
    flash_match = re.search(r"Flash:\s+.*used\s+(\d+) bytes from (\d+) bytes", output)
    if ram_match:
        footprint["ram_used_bytes"] = int(ram_match.group(1))
        footprint["ram_limit_bytes"] = int(ram_match.group(2))
    if flash_match:
        footprint["flash_used_bytes"] = int(flash_match.group(1))
        footprint["flash_limit_bytes"] = int(flash_match.group(2))
    return footprint


def _size_or_none(path: Path) -> int | None:
    return path.stat().st_size if path.exists() else None


def _classify_build_failure(output: str) -> str:
    lowered = output.lower()
    if (
        "region `ram'" in lowered
        or "region ram" in lowered
        or ("overflowed by" in lowered and ".dram" in lowered)
    ):
        return "activation_memory_overflow"
    if "region `flash'" in lowered or "region flash" in lowered or ".flash" in lowered:
        return "flash_memory_overflow"
    return "toolchain_version_skew"


def _adapter_for_cell(target: TargetConfig, project_dir: Path, *, flash: bool) -> CommandMCUAdapter:
    command = [
        "pio",
        "run",
        "-d",
        str(project_dir),
        "-e",
        target.platformio_env,
        "-t",
        "upload",
    ]
    firmware_path = project_dir / ".pio" / "build" / target.platformio_env / "firmware.bin"
    return CommandMCUAdapter(
        MCUAdapterConfig(
            target_id=target.name,
            serial_port=target.serial_port,
            firmware_path=firmware_path,
            flash_command=command,
            flash_before_prepare=flash,
            post_flash_delay_s=target.post_flash_delay_s,
        ),
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
    target_config: TargetConfig,
    task_spec: TaskSpec,
) -> tuple[Target, Task]:
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == target_config.name, Target.kind == "mcu"),
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name=target_config.name,
                kind="mcu",
                cpu=target_config.name,
                ram_mb=round(target_config.ram_bytes / (1024 * 1024)),
                storage_mb=round(target_config.flash_bytes / (1024 * 1024)),
                os_name="bare-metal",
                extra={"serial_port": target_config.serial_port},
            )
            session.add(target)
        task = session.scalar(
            select(Task).where(Task.name == task_spec.task_id, Task.version == "n3-v1"),
        )
        if task is None:
            task = Task(
                task_id=new_id(),
                name=task_spec.task_id,
                version="n3-v1",
                family=task_spec.metadata["family"],
                yaml_path=str(MANIFEST_PATH.relative_to(ROOT)),
                yaml_hash=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
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
    target_config: TargetConfig,
    task: Task,
    task_spec: TaskSpec,
    iterations: int,
    lineage: dict[str, Any],
    build: dict[str, Any],
    project_dir: Path,
    *,
    fnb58_enabled: bool,
    session_label: str | None,
    rerun_reason: str | None,
    topology: dict[str, Any] | None,
) -> None:
    extra = {
        "protocol": "n3",
        "model_lineage": lineage,
        "model_path": str(_variant_model_path(task_spec.task_id)),
        "project_dir": str(project_dir),
        "footprint": build["footprint"],
        "tflm_library": "Chirale_TensorFLowLite 2.0.0",
        "adapter": "CommandMCUAdapter",
    }
    if session_label:
        extra["session_label"] = session_label
        extra["session_tagged_at"] = dt.datetime.now(dt.UTC).isoformat()
    if rerun_reason:
        extra["rerun_reason"] = rerun_reason
    boundary_state = _boundary_state(target_config, fnb58_enabled=fnb58_enabled)
    if boundary_state is not None:
        if topology is not None:
            boundary_state |= topology
        extra["boundary_state"] = boundary_state
    with session_factory() as session:
        session.add(
            Run(
                run_id=run_id,
                target_id=target.target_id,
                task_id=task.task_id,
                started_at=dt.datetime.now(dt.UTC),
                status="running",
                corpus_tag="N3",
                warmup_count=0,
                measurement_count=iterations,
                signal_bench_version=__version__,
                runtime_name="TFLM",
                runtime_version="Chirale_TensorFLowLite-2.0.0",
                model_name=task_spec.task_id,
                model_hash=_variant_model_sha256(task_spec.task_id),
                quantization=str(task_spec.metadata["quantization"]),
                extra=extra,
                telemetry_partial=False,
            ),
        )
        session.commit()


def _boundary_state(target_config: TargetConfig, *, fnb58_enabled: bool) -> dict[str, Any] | None:
    if target_config.name != "f401re":
        return None
    return {
        "power_boundary": "full-board devkit via metered external 5 V rail",
        "authoritative_meter": "ina219",
        "cross_check_meter": "fnb58" if fnb58_enabled else None,
        "debug_interface": "ST-LINK virtual COM port",
        "debug_interface_state": "attached_enumerated",
        "serial_port": target_config.serial_port,
        "notes": [
            "ST-LINK USB is required for the F401RE serial benchmark protocol.",
            "ST-LINK/USB state is part of the disclosed F401RE power boundary.",
        ],
    }


def _write_results(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[InferenceResult],
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
                    accuracy_value=_result_accuracy_value(result.output),
                    extra={"output": result.output, "error": result.error},
                ),
            )
        session.commit()


def _mark_run_measurement_started(session_factory: sessionmaker[Session], run_id: str) -> None:
    with session_factory() as session:
        session.execute(
            update(Run).where(Run.run_id == run_id).values(started_at=dt.datetime.now(dt.UTC)),
        )
        session.commit()


def _finish_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[InferenceResult],
) -> None:
    with session_factory() as session:
        session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(
                finished_at=dt.datetime.now(dt.UTC),
                status="completed",
                measurement_count=len(results),
            ),
        )
        session.commit()


def _mark_run_failed(session_factory: sessionmaker[Session], run_id: str, error: str) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        extra = dict(run.extra or {}) if run is not None else {}
        extra["error"] = error
        session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(finished_at=dt.datetime.now(dt.UTC), status="failed", extra=extra),
        )
        session.commit()


def _result_accuracy_value(output: object) -> float | None:
    if isinstance(output, dict) and "correct" in output:
        return 1.0 if output["correct"] else 0.0
    return None


def _cell_metrics(
    session_factory: sessionmaker[Session],
    run_id: str,
    results: list[InferenceResult],
    lineage: dict[str, Any],
) -> dict[str, Any]:
    durations = [result.duration_us / 1000.0 for result in results if result.error is None]
    outputs = [result.output for result in results if result.error is None]
    latency = {
        "mean_ms": statistics.fmean(durations),
        "p50_ms": statistics.median(durations),
        "p99_ms": _percentile(durations, 99),
    }
    telemetry = _telemetry_counts(session_factory, run_id)
    wh_per_1000 = _wh_per_1000(session_factory, run_id, len(durations))
    return {
        "latency": latency,
        "accuracy_proxy": _accuracy_proxy(outputs, lineage),
        "wh_per_1000_inferences": wh_per_1000,
        "telemetry": telemetry,
    }


def _accuracy_proxy(outputs: list[object], lineage: dict[str, Any]) -> dict[str, Any]:
    retention = lineage["accuracy_retention"]
    if outputs and isinstance(outputs[0], dict) and "correct" in outputs[0]:
        correct = sum(1 for output in outputs if isinstance(output, dict) and output.get("correct"))
        proxy = correct / len(outputs)
        metric = "top1_subset"
    else:
        scored_outputs = [
            output for output in outputs if isinstance(output, Mapping) and "score" in output
        ]
        labeled_outputs = [
            output for output in outputs if isinstance(output, Mapping) and "label" in output
        ]
        scores = [float(output["score"]) for output in scored_outputs]
        labels = [int(output["label"]) for output in labeled_outputs]
        proxy = _auroc(scores, labels) if scores else float("nan")
        metric = "auroc_subset"
    return {
        "metric": metric,
        "value": proxy,
        "documented_metric": retention["metric"],
        "documented_variant": retention["variant"],
        "documented_retention": retention.get("delta_pp", retention.get("ratio")),
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


def _wh_per_1000(
    session_factory: sessionmaker[Session],
    run_id: str,
    inference_count: int,
) -> float | None:
    if inference_count <= 0:
        return None
    with session_factory() as session:
        samples = session.scalars(
            select(TelemetrySample)
            .where(
                TelemetrySample.run_id == run_id,
                TelemetrySample.source == "ina219",
                TelemetrySample.metric == "power",
            )
            .order_by(TelemetrySample.timestamp),
        ).all()
    if len(samples) < 2:
        return None
    joules = 0.0
    for previous, current in pairwise(samples):
        dt_s = (current.timestamp - previous.timestamp).total_seconds()
        if dt_s > 0:
            joules += ((previous.value + current.value) / 2.0) * dt_s
    wh = joules / 3600.0
    return wh / inference_count * 1000.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _auroc(scores: list[float], labels: list[int]) -> float:
    positives = [(score, label) for score, label in zip(scores, labels, strict=True) if label == 1]
    negatives = [(score, label) for score, label in zip(scores, labels, strict=True) if label == 0]
    if not positives or not negatives:
        return float("nan")
    wins = 0.0
    for positive_score, _ in positives:
        for negative_score, _ in negatives:
            if positive_score > negative_score:
                wins += 1.0
            elif positive_score == negative_score:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def _write_failure(
    session_factory: sessionmaker[Session],
    target: Target,
    task: Task,
    task_name: str,
    failure_mode: str,
    signature: str,
    context: dict[str, Any],
) -> None:
    with session_factory() as session:
        session.add(
            Failure(
                failure_id=new_id(),
                target_id=target.target_id,
                task_id=task.task_id,
                model_name=task_name,
                model_version=str(context.get("lineage", {}).get("model_version", "unknown")),
                corpus_tag="N3",
                failure_mode=failure_mode,
                diagnostic_signature=_last_lines(signature),
                toolchain_versions={
                    "platformio": _platformio_version(),
                    "signal_bench": __version__,
                },
                context=context,
            ),
        )
        session.commit()


def _platformio_version() -> str:
    process = subprocess.run(["pio", "--version"], text=True, capture_output=True, check=False)
    return process.stdout.strip() or process.stderr.strip() or "unknown"


def _summary_base(
    target_name: str,
    task_name: str,
    status: str,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "target": target_name,
        "task": task_name,
        "status": status,
        "corpus_tag": "N3",
        "model_lineage": {
            "path": str(LINEAGE_PATHS[task_name]),
            "derived_from": lineage["derived_from"],
            "prep_method": lineage["prep_method"],
            "accuracy_retention": lineage["accuracy_retention"],
        },
    }


def _last_lines(text: str, limit: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-limit:])


def _append_inventory(summary: dict[str, Any]) -> None:
    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INVENTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {summary['target']} / {summary['task']}\n\n")
        handle.write(f"- status: {summary['status']}\n")
        handle.write(f"- corpus_tag: {summary['corpus_tag']}\n")
        if "run_id" in summary:
            handle.write(f"- run_id: {summary['run_id']}\n")
            handle.write(f"- latency_ms: {summary['latency']}\n")
            handle.write(f"- Wh/1000: {summary['wh_per_1000_inferences']}\n")
            handle.write(f"- telemetry: {summary['telemetry']}\n")
            handle.write(f"- accuracy_proxy: {summary['accuracy_proxy']}\n")
        if "limiting_resource" in summary:
            handle.write(f"- limiting_resource: {summary['limiting_resource']}\n")
        handle.write(f"- footprint: {summary.get('footprint')}\n")


def _print_matrix(summaries: list[dict[str, Any]]) -> None:
    print("\nP3 MCU matrix")
    print("target,task,status,mean_ms,p50_ms,p99_ms,wh_per_1000")
    for summary in summaries:
        latency = summary.get("latency") or {}
        print(
            ",".join(
                [
                    summary["target"],
                    summary["task"],
                    summary["status"],
                    str(latency.get("mean_ms", "")),
                    str(latency.get("p50_ms", "")),
                    str(latency.get("p99_ms", "")),
                    str(summary.get("wh_per_1000_inferences", "")),
                ],
            ),
        )


if __name__ == "__main__":
    sys.exit(main())
