# SPDX-License-Identifier: Apache-2.0
"""NVIDIA NVML telemetry source."""

# ruff: noqa: ANN401, BLE001, PLC0415, TRY301

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

NVML_UNIT_HINTS = {"power": "W"}


@dataclass(frozen=True, slots=True)
class NvmlConfig:
    """Configuration for NVML GPU package-power polling."""

    name: str = "nvml"
    device_index: int = 0
    sample_rate_hz: float = 10.0


class NvmlSource(TelemetrySource):
    """Async source for NVIDIA GPU package power via NVML."""

    source_name = "nvml"
    sample_rate_hz = 10.0
    partial_coverage_threshold = 0.75

    def __init__(self: Self, config: NvmlConfig | None = None, *, nvml_module: Any = None) -> None:
        """Create an NVML source."""
        self._config = config or NvmlConfig()
        self.source_name = self._config.name
        self.sample_rate_hz = self._config.sample_rate_hz
        self._nvml = nvml_module
        self._handle: Any = None
        self._started = False
        self._stopping = True

    @property
    def name(self: Self) -> str:
        """Return the source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Initialize NVML and select a GPU."""
        if self._started:
            return
        nvml = self._nvml or _import_nvml()
        try:
            nvml.nvmlInit()
            count = int(nvml.nvmlDeviceGetCount())
            if count <= self._config.device_index:
                msg = f"NVML found {count} CUDA devices; need index {self._config.device_index}"
                raise SourceStartError(msg)
            self._handle = nvml.nvmlDeviceGetHandleByIndex(self._config.device_index)
        except SourceStartError:
            raise
        except Exception as exc:
            msg = f"failed to initialize NVML: {exc}"
            raise SourceStartError(msg) from exc
        self._nvml = nvml
        self._started = True
        self._stopping = False

    async def stop(self: Self) -> None:
        """Shutdown NVML."""
        self._stopping = True
        self._started = False
        nvml = self._nvml
        if nvml is None:
            return
        try:
            nvml.nvmlShutdown()
        except Exception:
            return

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield GPU package-power samples in watts."""
        if not self._started or self._nvml is None or self._handle is None:
            msg = "NvmlSource must be started before samples() is consumed"
            raise SourceStartError(msg)
        period_s = 1.0 / self._config.sample_rate_hz
        while not self._stopping:
            try:
                power_w = float(self._nvml.nvmlDeviceGetPowerUsage(self._handle)) / 1000.0
            except Exception as exc:
                msg = f"failed to read NVML power: {exc}"
                raise SourceDataError(msg) from exc
            if power_w <= 0:
                msg = f"NVML returned non-positive power: {power_w}"
                raise SourceDataError(msg)
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self._config.name,
                values={"power": power_w},
                unit_hints=NVML_UNIT_HINTS,
            )
            await asyncio.sleep(period_s)


def _import_nvml() -> Any:
    try:
        import pynvml
    except ImportError as exc:
        msg = "pynvml/nvidia-ml-py is required for NVML telemetry"
        raise SourceStartError(msg) from exc
    return pynvml
