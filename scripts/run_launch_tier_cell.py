# SPDX-License-Identifier: Apache-2.0
"""Run one launch-tier MCU reproduction cell from committed firmware sources."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from serial.tools import list_ports
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.adapters.exceptions import MeasureError, PrepareError
from signal_bench.adapters.mcu import CommandMCUAdapter, MCUAdapterConfig
from signal_bench.ids import new_id
from signal_bench.schema import Result, Run, Target, Task, TelemetrySample
from signal_bench.tasks import get_task
from signal_bench.telemetry.orchestrator import TelemetryOrchestrator
from signal_bench.telemetry.sources.bme280 import Bme280Config, Bme280Source
from signal_bench.telemetry.sources.fnirsi import FnirsiSource, FnirsiSourceConfig
from signal_bench.telemetry.sources.ina219 import Ina219Config, Ina219Source

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = ROOT / "src" / "signal_bench" / "firmware" / "launch-tier"
DEFAULT_DB = ROOT / "data" / "launch_tier_reproduction.db"
DEFAULT_OUTPUT_ROOT = ROOT / "results" / "launch_tier_reproduction"
TARGETS = ("esp32s3", "nano33", "f401re")
TASKS = ("kws", "ic", "ad")
NANO33_APP_USB_ID = (0x2341, 0x805A)
NANO33_BOOTLOADER_USB_ID = (0x2341, 0x005A)
NANO33_DEFAULT_IDLE_POWER_MAX_W = 0.060

TARGET_CONFIGS: dict[str, dict[str, Any]] = {
    "esp32s3": {
        "env": "esp32-s3-devkitc-1",
        "ram_bytes": 327_680,
        "flash_bytes": 3_342_336,
        "post_flash_delay_s": 0.0,
    },
    "nano33": {
        "env": "nano33ble",
        "ram_bytes": 262_144,
        "flash_bytes": 983_040,
        "post_flash_delay_s": 3.0,
    },
    "f401re": {
        "env": "nucleo_f401re",
        "ram_bytes": 98_304,
        "flash_bytes": 524_288,
        "post_flash_delay_s": 0.0,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--task", choices=TASKS, default="kws")
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--measurement-s", type=float, default=32.0)
    parser.add_argument("--probe-iterations", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=5000)
    parser.add_argument("--serial-reappear-timeout-s", type=float, default=20.0)
    parser.add_argument("--skip-state-preflight", action="store_true")
    parser.add_argument(
        "--nano33-idle-power-max-w", type=float, default=NANO33_DEFAULT_IDLE_POWER_MAX_W
    )
    parser.add_argument("--preflight-samples", type=int, default=12)
    parser.add_argument("--preflight-sample-interval-s", type=float, default=0.2)
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--no-fnb58", action="store_true")
    parser.add_argument("--fnb58-address", default="")
    parser.add_argument("--bme280-address", default="0x77")
    parser.add_argument("--ina219-address", default="0x40")
    parser.add_argument("--power-connector", required=True)
    parser.add_argument("--usb-routing", required=True)
    parser.add_argument("--debug-state", default="not applicable")
    parser.add_argument("--jp5-position", default="not applicable")
    parser.add_argument("--topology-note", action="append", default=[])
    parser.add_argument("--physical-routing-verified", action="store_true")
    parser.add_argument("--supply-setpoint-v", type=float)
    parser.add_argument("--fnb58-face-voltage-v", type=float)
    parser.add_argument("--fnb58-face-current-a", type=float)
    parser.add_argument("--fnb58-face-power-w", type=float)
    parser.add_argument("--operator-note", action="append", default=[])
    args = parser.parse_args()

    if not args.no_fnb58 and not args.fnb58_address:
        parser.error("--fnb58-address is required unless --no-fnb58 is set")

    summary = asyncio.run(_run(args))
    args.output_root.mkdir(parents=True, exist_ok=True)
    output_path = args.output_root / f"{summary['run_id']}.json"
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_record": str(output_path), **summary}, sort_keys=True))
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    target_config = TARGET_CONFIGS[args.target]
    project_dir = FIRMWARE_ROOT / f"{args.target}-{args.task}"
    env = str(target_config["env"])
    if not project_dir.exists():
        raise SystemExit(f"missing committed launch-tier firmware project: {project_dir}")

    build = _run_command(["pio", "run", "-d", str(project_dir), "-e", env])
    if build["returncode"] != 0:
        raise SystemExit(_last_lines(build["output"], 30))

    if not args.skip_upload:
        upload = _run_command(
            [
                "pio",
                "run",
                "-d",
                str(project_dir),
                "-e",
                env,
                "-t",
                "upload",
                "--upload-port",
                args.serial_port,
            ],
        )
        if upload["returncode"] != 0:
            raise SystemExit(_last_lines(upload["output"], 30))
        _wait_for_serial_port(Path(args.serial_port), args.serial_reappear_timeout_s)
    else:
        upload = {"returncode": 0, "output": "upload skipped"}
    preflight = _state_preflight(args)

    _ensure_database(args.db)
    engine = create_engine(f"sqlite:///{args.db}")
    session_factory = sessionmaker(bind=engine)
    try:
        target_row, task_row = _ensure_target_task(session_factory, args, target_config)
        adapter = _adapter(args, project_dir, env, flash=False)
        task_spec = get_task(args.task)
        try:
            await adapter.prepare(new_id())
            probe_results = [
                result async for result in adapter.measure(task_spec, args.probe_iterations)
            ]
            probe_durations = [
                result.duration_us for result in probe_results if result.error is None
            ]
            if not probe_durations:
                raise MeasureError("probe produced no successful inference results")
            probe_mean_us = statistics.fmean(probe_durations)
            iterations = max(
                1,
                min(args.max_iterations, math.ceil(args.measurement_s * 1_000_000 / probe_mean_us)),
            )
        finally:
            await adapter.teardown()

        run_id = new_id()
        _create_run(
            session_factory,
            run_id,
            target_row,
            task_row,
            args,
            target_config,
            build,
            upload,
            preflight,
            project_dir,
            iterations,
        )
        telemetry = TelemetryOrchestrator(session_factory)
        adapter = _adapter(args, project_dir, env, flash=False)
        results = []
        try:
            await adapter.prepare(run_id)
            await telemetry.start_run(run_id, _telemetry_sources(args))
            _mark_measurement_started(session_factory, run_id)
            results.extend([result async for result in adapter.measure(task_spec, iterations)])
        except (MeasureError, PrepareError) as exc:
            _mark_failed(session_factory, run_id, str(exc))
            raise
        finally:
            telemetry_state = await telemetry.stop_run()
            await adapter.teardown()

        _write_results(session_factory, run_id, results)
        _finish_run(session_factory, run_id, results)
        return _summary(session_factory, run_id, args, build, telemetry_state.partial)
    finally:
        engine.dispose()


def _adapter(
    args: argparse.Namespace,
    project_dir: Path,
    env: str,
    *,
    flash: bool,
) -> CommandMCUAdapter:
    command_line = [
        "pio",
        "run",
        "-d",
        str(project_dir),
        "-e",
        env,
        "-t",
        "upload",
        "--upload-port",
        args.serial_port,
    ]
    firmware_path = project_dir / ".pio" / "build" / env / "firmware.bin"
    return CommandMCUAdapter(
        MCUAdapterConfig(
            target_id=args.target,
            serial_port=args.serial_port,
            firmware_path=firmware_path,
            flash_command=command_line,
            flash_before_prepare=flash,
            post_flash_delay_s=float(TARGET_CONFIGS[args.target]["post_flash_delay_s"]),
        ),
    )


def _telemetry_sources(args: argparse.Namespace) -> list[Any]:
    sources: list[Any] = [
        Ina219Source(Ina219Config(address=int(str(args.ina219_address), 0))),
        Bme280Source(Bme280Config(address=int(str(args.bme280_address), 0))),
    ]
    if not args.no_fnb58:
        sources.append(FnirsiSource(FnirsiSourceConfig(address=args.fnb58_address)))
    return sources


def _wait_for_serial_port(serial_port: Path, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if serial_port.exists():
            time.sleep(1.0)
            return
        time.sleep(0.25)
    raise SystemExit(
        f"serial port did not reappear after upload within {timeout_s:.1f}s: {serial_port}",
    )


def _state_preflight(args: argparse.Namespace) -> dict[str, Any]:
    if args.skip_state_preflight:
        return {"skipped": True, "reason": "--skip-state-preflight"}
    if args.target != "nano33":
        return {
            "skipped": True,
            "reason": "target has no launch-tier state gate",
            "serial": _serial_port_identity(args.serial_port),
        }
    usb_state = _nano33_usb_state(args.serial_port)
    if usb_state["vid_pid"] == _format_usb_id(NANO33_BOOTLOADER_USB_ID):
        raise SystemExit(
            "Nano 33 is in bootloader USB state "
            f"{usb_state['vid_pid']} on {args.serial_port}; restore the app before measuring.",
        )
    if usb_state["vid_pid"] != _format_usb_id(NANO33_APP_USB_ID):
        raise SystemExit(
            "Nano 33 serial port is not in the expected app USB state "
            f"{_format_usb_id(NANO33_APP_USB_ID)}: {usb_state}",
        )
    power = _ina219_preflight_power(
        int(str(args.ina219_address), 0),
        args.preflight_samples,
        args.preflight_sample_interval_s,
    )
    if power["avg_power_w"] > args.nano33_idle_power_max_w:
        raise SystemExit(
            "Nano 33 preflight rejected high-current app state: "
            f"avg_power_w={power['avg_power_w']:.6f}, "
            f"limit_w={args.nano33_idle_power_max_w:.6f}. "
            "Restore the app with a clean upload or full rail/USB power-cycle before measuring.",
        )
    return {
        "skipped": False,
        "target": args.target,
        "usb": usb_state,
        "serial": _serial_port_identity(args.serial_port),
        "ina219_idle": power,
        "idle_power_limit_w": args.nano33_idle_power_max_w,
    }


def _nano33_usb_state(serial_port: str) -> dict[str, Any]:
    state = _serial_port_identity(serial_port)
    if state["present"] is not True:
        raise SystemExit(f"serial port is not present: {serial_port}")
    return state


def _serial_port_identity(serial_port: str) -> dict[str, Any]:
    port = next((item for item in list_ports.comports() if item.device == serial_port), None)
    if port is None:
        return {"device": serial_port, "present": False}
    vid_pid = None
    if port.vid is not None and port.pid is not None:
        vid_pid = _format_usb_id((int(port.vid), int(port.pid)))
    return {
        "device": port.device,
        "present": True,
        "description": port.description,
        "hardware_id": port.hwid,
        "vid_pid": vid_pid,
        "serial_number": port.serial_number,
        "location": port.location,
        "manufacturer": port.manufacturer,
        "product": port.product,
        "interface": port.interface,
    }


def _format_usb_id(vid_pid: tuple[int, int]) -> str:
    return f"{vid_pid[0]:04X}:{vid_pid[1]:04X}"


def _ina219_preflight_power(address: int, samples: int, interval_s: float) -> dict[str, Any]:
    if samples <= 0:
        raise SystemExit("--preflight-samples must be positive")
    try:
        import board
        import busio
        from adafruit_ina219 import INA219
    except Exception as exc:
        raise SystemExit(f"INA219 preflight dependencies unavailable: {exc}") from exc
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        sensor = INA219(i2c, addr=address)
        power_values = []
        current_values = []
        voltage_values = []
        for _ in range(samples):
            voltage_values.append(float(sensor.bus_voltage))
            current_values.append(float(sensor.current) / 1000.0)
            power_values.append(float(sensor.power))
            time.sleep(max(0.0, interval_s))
    except Exception as exc:
        raise SystemExit(f"INA219 preflight read failed at 0x{address:02x}: {exc}") from exc
    return {
        "samples": samples,
        "avg_voltage_v": statistics.fmean(voltage_values),
        "avg_current_a": statistics.fmean(current_values),
        "avg_power_w": statistics.fmean(power_values),
        "min_power_w": min(power_values),
        "max_power_w": max(power_values),
    }


def _ensure_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/signal_bench/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _ensure_target_task(
    session_factory: sessionmaker[Session],
    args: argparse.Namespace,
    target_config: dict[str, Any],
) -> tuple[Target, Task]:
    task_spec = get_task(args.task)
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == args.target, Target.kind == "mcu")
        )
        if target is None:
            target = Target(
                target_id=new_id(),
                name=args.target,
                kind="mcu",
                cpu=args.target,
                ram_mb=round(int(target_config["ram_bytes"]) / (1024 * 1024)),
                storage_mb=round(int(target_config["flash_bytes"]) / (1024 * 1024)),
                os_name="bare-metal",
                extra={"serial_port": args.serial_port},
            )
            session.add(target)
        task = session.scalar(
            select(Task).where(Task.name == args.task, Task.version == "launch-tier")
        )
        if task is None:
            manifest = ROOT / "models" / "reference" / "manifest.yaml"
            task = Task(
                task_id=new_id(),
                name=args.task,
                version="launch-tier",
                family=task_spec.metadata["family"],
                yaml_path=str(manifest.relative_to(ROOT)),
                yaml_hash=hashlib.sha256(manifest.read_bytes()).hexdigest(),
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
    args: argparse.Namespace,
    target_config: dict[str, Any],
    build: dict[str, Any],
    upload: dict[str, Any],
    preflight: dict[str, Any],
    project_dir: Path,
    iterations: int,
) -> None:
    extra = {
        "protocol": "launch-tier-reproduction",
        "measurement_window_s": args.measurement_s,
        "probe_iterations": args.probe_iterations,
        "firmware_project": str(project_dir.relative_to(ROOT)),
        "platformio_env": target_config["env"],
        "toolchain": _toolchain_manifest(project_dir, str(target_config["env"])),
        "host": _host_manifest(),
        "build": _command_summary(build),
        "upload": _command_summary(upload),
        "state_preflight": preflight,
        "device_identity": {
            "serial_port": _serial_port_identity(args.serial_port),
        },
        "telemetry_config": {
            "ina219_address": f"0x{int(str(args.ina219_address), 0):02x}",
            "bme280_address": f"0x{int(str(args.bme280_address), 0):02x}",
            "fnb58_transport": None if args.no_fnb58 else "ble",
            "fnb58_address_recorded": None if args.no_fnb58 else bool(args.fnb58_address),
        },
        "operator_observations": {
            "physical_routing_verified": bool(args.physical_routing_verified),
            "supply_setpoint_v": args.supply_setpoint_v,
            "fnb58_face_voltage_v": args.fnb58_face_voltage_v,
            "fnb58_face_current_a": args.fnb58_face_current_a,
            "fnb58_face_power_w": args.fnb58_face_power_w,
            "notes": list(args.operator_note),
        },
        "boundary_state": {
            "authoritative_meter": "ina219",
            "cross_check_meter": None if args.no_fnb58 else "fnb58",
            "power_connector_used": args.power_connector,
            "usb_vbus_routing": args.usb_routing,
            "debug_interface_state": args.debug_state,
            "jp5_position": args.jp5_position,
            "notes": list(args.topology_note),
        },
    }
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
                git_sha=_git_sha(),
                signal_bench_version=__version__,
                runtime_name="TFLM",
                runtime_version="Chirale_TensorFLowLite-2.0.0",
                model_name=args.task,
                model_hash=_hash_model_source(project_dir),
                quantization=str(get_task(args.task).metadata["quantization"]),
                telemetry_partial=False,
                extra=extra,
            ),
        )
        session.commit()


def _mark_measurement_started(session_factory: sessionmaker[Session], run_id: str) -> None:
    with session_factory() as session:
        session.execute(
            update(Run).where(Run.run_id == run_id).values(started_at=dt.datetime.now(dt.UTC))
        )
        session.commit()


def _write_results(
    session_factory: sessionmaker[Session], run_id: str, results: Sequence[Any]
) -> None:
    with session_factory() as session:
        for result in results:
            duration_ms = result.duration_us / 1000.0
            output = result.output if result.error is None else None
            session.add(
                Result(
                    result_id=new_id(),
                    run_id=run_id,
                    sequence=result.iter_id,
                    started_at=result.timestamp,
                    duration_ms=duration_ms,
                    throughput_unit="inferences/s",
                    throughput_value=1000 / duration_ms if duration_ms > 0 else None,
                    accuracy_value=_accuracy_value(output),
                    extra={"output": output, "error": result.error},
                ),
            )
        session.commit()


def _finish_run(
    session_factory: sessionmaker[Session], run_id: str, results: Sequence[Any]
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


def _mark_failed(session_factory: sessionmaker[Session], run_id: str, error: str) -> None:
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


def _summary(
    session_factory: sessionmaker[Session],
    run_id: str,
    args: argparse.Namespace,
    build: dict[str, Any],
    telemetry_partial: bool,
) -> dict[str, Any]:
    with session_factory() as session:
        run = session.get(Run, run_id)
        powers = session.scalars(
            select(TelemetrySample)
            .where(
                TelemetrySample.run_id == run_id,
                TelemetrySample.source == "ina219",
                TelemetrySample.metric == "power",
            )
            .order_by(TelemetrySample.timestamp),
        ).all()
        fnb58 = session.scalars(
            select(TelemetrySample)
            .where(
                TelemetrySample.run_id == run_id,
                TelemetrySample.source == "fnb58",
                TelemetrySample.metric == "power",
            )
            .order_by(TelemetrySample.timestamp),
        ).all()
        results = session.scalars(select(Result).where(Result.run_id == run_id)).all()
    durations = [result.duration_ms for result in results]
    return {
        "run_id": run_id,
        "target": args.target,
        "task": args.task,
        "status": run.status if run else "unknown",
        "telemetry_partial": telemetry_partial,
        "measurement_count": len(results),
        "latency_ms": _series_stats(durations),
        "ina219": _power_summary(powers, len(results)),
        "fnb58": _power_summary(fnb58, len(results)) if fnb58 else None,
        "environment": (run.extra or {}).get("host") if run else _host_manifest(),
        "toolchain": (run.extra or {}).get("toolchain") if run else {},
        "boundary_state": (run.extra or {}).get("boundary_state") if run else {},
        "state_preflight": (run.extra or {}).get("state_preflight") if run else {},
        "device_identity": (run.extra or {}).get("device_identity") if run else {},
        "telemetry_config": (run.extra or {}).get("telemetry_config") if run else {},
        "operator_observations": (run.extra or {}).get("operator_observations") if run else {},
        "firmware_footprint": _parse_footprint(build["output"]),
    }


def _power_summary(
    samples: Sequence[TelemetrySample], inference_count: int
) -> dict[str, Any] | None:
    if len(samples) < 2 or inference_count <= 0:
        return None
    joules = 0.0
    for previous, current in pairwise(samples):
        dt_s = (current.timestamp - previous.timestamp).total_seconds()
        if dt_s > 0:
            joules += ((previous.value + current.value) / 2.0) * dt_s
    powers = [sample.value for sample in samples]
    wh = joules / 3600.0
    return {
        "sample_count": len(samples),
        "avg_power_w": statistics.fmean(powers),
        "min_power_w": min(powers),
        "max_power_w": max(powers),
        "wh_per_1000": wh / inference_count * 1000.0,
    }


def _series_stats(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "p50": None, "mean": None, "stddev": None}
    return {
        "n": len(values),
        "p50": statistics.median(values),
        "mean": statistics.fmean(values),
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def _accuracy_value(output: object) -> float | None:
    if isinstance(output, dict) and "correct" in output:
        return 1.0 if output["correct"] else 0.0
    return None


def _run_command(command_line: list[str]) -> dict[str, Any]:
    process = subprocess.run(
        command_line,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {"returncode": process.returncode, "output": process.stdout, "command": command_line}


def _command_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": result["command"] if "command" in result else None,
        "returncode": result["returncode"],
        "tail": _last_lines(result["output"], 20),
    }


def _parse_footprint(output: str) -> dict[str, int]:
    import re

    footprint: dict[str, int] = {}
    ram_match = re.search(r"RAM:\s+.*used\s+(\d+) bytes from (\d+) bytes", output)
    flash_match = re.search(r"Flash:\s+.*used\s+(\d+) bytes from (\d+) bytes", output)
    if ram_match:
        footprint["ram_used_bytes"] = int(ram_match.group(1))
        footprint["ram_limit_bytes"] = int(ram_match.group(2))
    if flash_match:
        footprint["flash_used_bytes"] = int(flash_match.group(1))
        footprint["flash_limit_bytes"] = int(flash_match.group(2))
    return footprint


def _toolchain_manifest(project_dir: Path, env: str) -> dict[str, Any]:
    pio = _run_command(["pio", "--version"])
    packages = _run_command(["pio", "pkg", "list", "-d", str(project_dir), "-e", env])
    return {
        "platformio": (pio["output"].strip() or "unknown"),
        "platformio_packages": packages["output"].strip().splitlines(),
    }


def _host_manifest() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "system": platform.system(),
        "release": platform.release(),
    }


def _git_sha() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _hash_model_source(project_dir: Path) -> str:
    return hashlib.sha256((project_dir / "src" / "model_data.cc").read_bytes()).hexdigest()


def _last_lines(text: str, limit: int) -> str:
    return "\n".join(text.strip().splitlines()[-limit:])


if __name__ == "__main__":
    raise SystemExit(main())
