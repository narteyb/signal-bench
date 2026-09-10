# SPDX-License-Identifier: Apache-2.0
"""Hailo-10H adapter using the pyHailoRT InferModel API."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

from signal_bench.adapters.base import (
    Adapter,
    AdapterConfig,
    InferenceResult,
    OSInfo,
    ThermalReading,
)
from signal_bench.adapters.exceptions import ConfigurationError, MeasureError, PrepareError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from signal_bench.adapters.mcu.task import TaskSpec

NPU_NOT_READY_MESSAGE = (
    "NPU not ready — /dev/hailo0 missing or wrong arch. After any kernel/apt upgrade run: "
    "sudo dkms autoinstall -k $(uname -r) && sudo modprobe hailo1x_pci"
)
MAX_INLINE_OUTPUT_VALUES = 4096


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
PathExists = Callable[[Path], bool]


@dataclass(frozen=True, slots=True, kw_only=True)
class HailoAdapterConfig(AdapterConfig):
    """Configuration for a local Hailo-10H pyHailoRT adapter."""

    hef_path: Path
    batch_size: int = 1
    input_format_type: str = "FLOAT32"
    output_format_type: str = "UINT8"
    timeout_ms: int = 10_000
    warmup_iterations: int = 1
    input_fill_value: float = 0.0


@dataclass(frozen=True, slots=True)
class HailoPreflightInfo:
    """Verified NPU identity from the Hailo runtime preflight."""

    architecture: str
    firmware_version: str
    identify_output: str


class HailoAdapter(Adapter):
    """Run prebuilt HEF files on a local Hailo-10H through pyHailoRT.

    This adapter is intended to run on the Raspberry Pi that owns ``/dev/hailo0``.
    Host-side runners may invoke it remotely over SSH, but the HailoRT API calls
    themselves are local to the Pi.
    """

    def __init__(
        self: Self,
        config: HailoAdapterConfig,
        *,
        command_runner: CommandRunner | None = None,
        path_exists: PathExists | None = None,
    ) -> None:
        """Create the adapter without touching Hailo hardware."""
        super().__init__(config)
        if config.batch_size <= 0:
            msg = "HailoAdapterConfig.batch_size must be positive"
            raise ConfigurationError(msg)
        if config.timeout_ms <= 0:
            msg = "HailoAdapterConfig.timeout_ms must be positive"
            raise ConfigurationError(msg)
        if config.warmup_iterations < 0:
            msg = "HailoAdapterConfig.warmup_iterations must be non-negative"
            raise ConfigurationError(msg)
        self.config: HailoAdapterConfig = config
        self._command_runner = command_runner or _run_command
        self._path_exists = path_exists or Path.exists
        self._preflight: HailoPreflightInfo | None = None
        self._run_id: str | None = None
        self._prepared = False

    async def prepare(self: Self, run_id: str) -> None:
        """Validate HEF path and fail loudly if the Hailo-10H is not ready."""
        await asyncio.wait_for(self._prepare(run_id), timeout=self.config.timeouts.prepare_s)

    async def warmup(self: Self) -> None:
        """Run optional unrecorded warmup inferences."""
        if self.config.warmup_iterations <= 0:
            return
        await asyncio.wait_for(
            asyncio.to_thread(self._run_inferences_sync, self.config.warmup_iterations),
            timeout=self.config.timeouts.warmup_s,
        )

    async def measure(
        self: Self,
        task: TaskSpec,
        iterations: int,
    ) -> AsyncIterator[InferenceResult]:
        """Run measured Hailo inferences and yield one result per `cim.run()`."""
        _ = task
        if iterations <= 0:
            msg = "iterations must be positive"
            raise MeasureError(msg)
        if not self._prepared:
            msg = "HailoAdapter.measure called before prepare"
            raise MeasureError(msg)
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(self._run_inferences_sync, iterations, task.input_data_path),
                timeout=self.config.timeouts.measure_per_iteration_s * iterations,
            )
        except TimeoutError as exc:
            msg = "Hailo measurement timed out"
            raise MeasureError(msg) from exc
        except Exception as exc:
            msg = f"Hailo measurement failed: {exc}"
            raise MeasureError(msg) from exc

        for result in results:
            yield result

    async def read_thermal(self: Self) -> ThermalReading:
        """Return unavailable thermal data; ambient telemetry is captured separately."""
        return ThermalReading(available=False)

    async def os_info(self: Self) -> OSInfo:
        """Return Hailo runtime and firmware metadata captured during preflight."""
        preflight = self._preflight
        if preflight is None:
            msg = "HailoAdapter.os_info called before prepare"
            raise PrepareError(msg)
        return OSInfo(
            target_name=self.config.target_id,
            firmware_version=preflight.firmware_version,
            additional=self.metadata(),
        )

    async def teardown(self: Self) -> None:
        """Mark the adapter idle; Hailo resources are scoped per measurement call."""
        self._prepared = False
        self._run_id = None

    def metadata(self: Self) -> dict[str, str]:
        """Return run metadata required for NPU runs."""
        preflight = self._preflight
        metadata = {
            "adapter": "HailoAdapter",
            "hef_path": str(self.config.hef_path),
            "hef_name": self.config.hef_path.name,
            "batch_size": str(self.config.batch_size),
            "input_format_type": self.config.input_format_type,
            "output_format_type": self.config.output_format_type,
            "kernel_version": _command_text(self._command_runner, ["uname", "-r"]),
            "hailort_version": _command_text(self._command_runner, ["hailortcli", "--version"]),
            "pcie_link": _pcie_link_summary(self._command_runner),
        }
        if preflight is not None:
            metadata["hailo_architecture"] = preflight.architecture
            metadata["hailo_firmware_version"] = preflight.firmware_version
        return metadata

    async def _prepare(self: Self, run_id: str) -> None:
        if not self._path_exists(self.config.hef_path):
            msg = f"HEF file not found: {self.config.hef_path}"
            raise PrepareError(msg)
        self._preflight = preflight_hailo10h(
            command_runner=self._command_runner,
            path_exists=self._path_exists,
        )
        self._run_id = run_id
        self._prepared = True

    def _run_inferences_sync(
        self: Self,
        iterations: int,
        input_data_path: Path | None = None,
    ) -> list[InferenceResult]:
        hailo_platform = importlib.import_module("hailo_platform")
        np = importlib.import_module("numpy")

        vdevice_cls = hailo_platform.VDevice
        scheduling_algorithm = hailo_platform.HailoSchedulingAlgorithm
        format_type_cls = hailo_platform.FormatType

        params = vdevice_cls.create_params()
        params.scheduling_algorithm = scheduling_algorithm.ROUND_ROBIN

        input_format = getattr(format_type_cls, self.config.input_format_type)
        output_format = getattr(format_type_cls, self.config.output_format_type)
        input_dtype = _numpy_dtype_for_format(np, self.config.input_format_type)
        output_dtype = _numpy_dtype_for_format(np, self.config.output_format_type)
        input_samples = _load_input_samples(np, input_data_path)

        results: list[InferenceResult] = []
        with vdevice_cls(params) as vdev:
            infer_model = vdev.create_infer_model(str(self.config.hef_path))
            infer_model.set_batch_size(self.config.batch_size)
            infer_model.input().set_format_type(input_format)
            infer_model.output().set_format_type(output_format)
            with infer_model.configure() as configured:
                for iter_id in range(iterations):
                    bindings = configured.create_bindings()
                    input_buffer = _input_buffer_for_iteration(
                        np,
                        infer_model.input().shape,
                        input_dtype,
                        self.config.input_fill_value,
                        input_samples,
                        iter_id,
                    )
                    output_buffer = np.empty(infer_model.output().shape, dtype=output_dtype)
                    started = dt.datetime.now(tz=dt.UTC)
                    t0 = time.perf_counter()
                    bindings.input().set_buffer(input_buffer)
                    bindings.output().set_buffer(output_buffer)
                    configured.run([bindings], self.config.timeout_ms)
                    duration_us = round((time.perf_counter() - t0) * 1_000_000)
                    results.append(
                        InferenceResult(
                            iter_id=iter_id,
                            output=_summarize_output(output_buffer),
                            duration_us=duration_us,
                            timestamp=started,
                        ),
                    )
        return results


def preflight_hailo10h(
    *,
    command_runner: CommandRunner | None = None,
    path_exists: PathExists | None = None,
) -> HailoPreflightInfo:
    """Verify `/dev/hailo0` exists and HailoRT identifies HAILO10H."""
    runner = command_runner or _run_command
    exists = path_exists or Path.exists
    if not exists(Path("/dev/hailo0")):
        raise PrepareError(NPU_NOT_READY_MESSAGE)

    completed = runner(["hailortcli", "fw-control", "identify"])
    output = _combined_output(completed)
    if completed.returncode != 0 or "Device Architecture: HAILO10H" not in output:
        raise PrepareError(NPU_NOT_READY_MESSAGE)

    architecture = _field_from_identify(output, "Device Architecture") or "unknown"
    firmware = _field_from_identify(output, "Firmware Version") or "unknown"
    return HailoPreflightInfo(
        architecture=architecture,
        firmware_version=firmware,
        identify_output=output,
    )


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed HailoRT argv; shell is never used.
        command,
        text=True,
        capture_output=True,
        check=False,
    )


def _combined_output(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()


def _field_from_identify(output: str, field_name: str) -> str | None:
    prefix = f"{field_name}:"
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _command_text(runner: CommandRunner, command: Sequence[str]) -> str:
    completed = runner(command)
    return _combined_output(completed) or "unknown"


def _pcie_link_summary(runner: CommandRunner) -> str:
    for command in (
        ["sudo", "-n", "lspci", "-nnvvv", "-s", "0001:01:00.0"],
        ["lspci", "-nnvvv", "-s", "0001:01:00.0"],
    ):
        completed = runner(command)
        output = _combined_output(completed)
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("LnkSta:"):
                return stripped.removeprefix("LnkSta:").strip()
    return "unknown"


def _numpy_dtype_for_format(np: object, format_name: str) -> object:
    np_module = cast("Any", np)
    mapping = {
        "FLOAT32": np_module.float32,
        "UINT8": np_module.uint8,
        "UINT16": np_module.uint16,
        "INT8": np_module.int8,
        "INT16": np_module.int16,
    }
    try:
        return mapping[format_name]
    except KeyError as exc:
        choices = ", ".join(sorted(mapping))
        msg = f"Unsupported Hailo FormatType {format_name!r}; supported: {choices}"
        raise ConfigurationError(msg) from exc


def _load_input_samples(np: object, path: Path | None) -> object | None:
    if path is None or str(path) == "/dev/null":
        return None
    np_module = cast("Any", np)
    if not path.exists():
        msg = f"Hailo input data file not found: {path}"
        raise ConfigurationError(msg)
    if path.suffix == ".npz":
        archive = np_module.load(path, allow_pickle=False)
        if "inputs" not in archive:
            msg = f"Hailo input npz must contain an 'inputs' array: {path}"
            raise ConfigurationError(msg)
        return cast("object", archive["inputs"])
    return cast("object", np_module.load(path, allow_pickle=False))


def _input_buffer_for_iteration(  # noqa: PLR0913
    np: object,
    input_shape: Sequence[int],
    input_dtype: object,
    fill_value: float,
    input_samples: object | None,
    iter_id: int,
) -> object:
    np_module = cast("Any", np)
    if input_samples is None:
        buffer = np_module.empty(input_shape, dtype=input_dtype)
        buffer.fill(fill_value)
        return buffer

    samples = cast("Any", input_samples)
    sample = samples[iter_id % len(samples)].astype(input_dtype, copy=False)
    if tuple(sample.shape) == tuple(input_shape):
        return np_module.array(sample, dtype=input_dtype, copy=True)
    if len(input_shape) >= 1 and tuple(sample.shape) == tuple(input_shape[1:]):
        buffer = np_module.empty(input_shape, dtype=input_dtype)
        for batch_index in range(input_shape[0]):
            buffer[batch_index] = samples[(iter_id + batch_index) % len(samples)].astype(
                input_dtype,
                copy=False,
            )
        return buffer
    msg = (
        f"Input sample shape {tuple(sample.shape)} does not match "
        f"HEF input shape {tuple(input_shape)}"
    )
    raise ConfigurationError(msg)


def _summarize_output(output_buffer: object) -> dict[str, object]:
    buffer = cast("Any", output_buffer)
    flat = buffer.reshape(-1)
    shape = list(buffer.shape)
    dtype = str(buffer.dtype)
    if flat.size == 0:
        return {"shape": shape, "size": 0}
    argmax = int(flat.argmax())
    summary = {
        "shape": shape,
        "dtype": dtype,
        "argmax": argmax,
        "max": float(flat[argmax]),
        "min": float(flat.min()),
        "sum": float(flat.sum()),
        "preview": json.loads(json.dumps(flat[: min(8, flat.size)].tolist())),
    }
    if flat.size <= MAX_INLINE_OUTPUT_VALUES:
        summary["values"] = json.loads(json.dumps(flat.tolist()))
    return summary
