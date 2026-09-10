# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for adapter base-class tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from signal_bench.adapters.base import ThermalReading, TimeoutConfig
from signal_bench.adapters.mcu.base import MCUAdapterBase
from signal_bench.adapters.mcu.config import MCUAdapterConfig
from signal_bench.adapters.mcu.task import TaskSpec

if TYPE_CHECKING:
    from collections.abc import Awaitable

T = TypeVar("T")


class TestMCUAdapter(MCUAdapterBase):
    """Test-only concrete subclass for exercising `MCUAdapterBase` behavior."""

    __test__ = False

    def __init__(
        self,
        config: MCUAdapterConfig,
        *,
        firmware_version: str = "test-firmware-v0",
        flash_delay_s: float = 0.0,
        firmware_delay_s: float = 0.0,
    ) -> None:
        """Create a test adapter with controllable hook behavior."""
        super().__init__(config)
        self.firmware_version = firmware_version
        self.flash_delay_s = flash_delay_s
        self.firmware_delay_s = firmware_delay_s
        self.flash_calls = 0
        self.firmware_version_calls = 0

    async def _flash_firmware(self) -> None:
        """Record a flash hook call without touching hardware."""
        self.flash_calls += 1
        if self.flash_delay_s:
            await asyncio.sleep(self.flash_delay_s)

    async def _get_firmware_version(self) -> str:
        """Return a canned firmware version for OS info tests."""
        self.firmware_version_calls += 1
        if self.firmware_delay_s:
            await asyncio.sleep(self.firmware_delay_s)
        return self.firmware_version


class ThermalTestMCUAdapter(TestMCUAdapter):
    """Test adapter variant that overrides thermal reporting."""

    __test__ = False

    def __init__(
        self,
        config: MCUAdapterConfig,
        thermal_reading: ThermalReading,
    ) -> None:
        """Create a test adapter with a fixed thermal reading."""
        super().__init__(config)
        self.thermal_reading = thermal_reading

    async def read_thermal(self) -> ThermalReading:
        """Return the fixed thermal reading."""
        return self.thermal_reading


def make_mcu_config(  # noqa: PLR0913 - compact fixture factory mirrors config fields
    *,
    target_id: str = "test-mcu",
    serial_port: str = "mock://mcu",
    baud_rate: int = 115_200,
    flash_before_prepare: bool = False,
    prepare_s: float = 1.0,
    warmup_s: float = 1.0,
    measure_per_iteration_s: float = 1.0,
    teardown_s: float = 1.0,
) -> MCUAdapterConfig:
    """Build a compact MCU config for unit tests."""
    return MCUAdapterConfig(
        target_id=target_id,
        serial_port=serial_port,
        baud_rate=baud_rate,
        flash_before_prepare=flash_before_prepare,
        timeouts=TimeoutConfig(
            prepare_s=prepare_s,
            warmup_s=warmup_s,
            measure_per_iteration_s=measure_per_iteration_s,
            teardown_s=teardown_s,
        ),
    )


def make_task(task_id: str = "kws") -> TaskSpec:
    """Build a minimal task spec for measurement tests."""
    return TaskSpec(
        task_id=task_id,
        model_path=Path("model.tflite"),
        input_data_path=Path("input.wav"),
    )


async def with_test_timeout(awaitable: Awaitable[T], timeout_s: float = 10.0) -> T:
    """Bound an async unit-test operation so hangs fail quickly."""
    return await asyncio.wait_for(awaitable, timeout=timeout_s)
