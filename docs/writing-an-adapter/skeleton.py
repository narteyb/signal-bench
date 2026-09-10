# SPDX-License-Identifier: Apache-2.0
"""No-hardware adapter skeleton for new signal-bench target adapters.

This file is intentionally small and runnable. Replace the in-memory command
simulation with your target's UART, BLE, GPIO, or flashing code while keeping
the public lifecycle methods and exception semantics intact.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from signal_bench.adapters import (
    Adapter,
    AdapterConfig,
    ConfigurationError,
    InferenceResult,
    MeasureError,
    OSInfo,
    PrepareError,
    TaskSpec,
    ThermalReading,
    WarmupError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, kw_only=True)
class MockSerialAdapterConfig(AdapterConfig):
    """Configuration for the example adapter.

    Real adapters usually add fields such as `serial_port`, `baud_rate`,
    `firmware_path`, or `reset_gpio`. Keep those fields on the config object so
    invalid setup can fail before the run lifecycle begins.
    """

    firmware_version: str = "mock-firmware-0"
    duration_us_base: int = 1_000


class MockSerialAdapter(Adapter):
    """Minimal target adapter that simulates a UART-driven MCU benchmark."""

    def __init__(self, config: MockSerialAdapterConfig) -> None:
        """Validate and store mock adapter configuration."""
        super().__init__(config)
        if config.duration_us_base <= 0:
            msg = "duration_us_base must be positive"
            raise ConfigurationError(msg)
        self._mock_config = config
        self._prepared = False
        self._run_id: str | None = None

    async def prepare(self, run_id: str) -> None:
        """Open connections, flash firmware if needed, and reset the target."""
        if self._prepared:
            return
        if not run_id:
            msg = "run_id is required"
            raise PrepareError(msg)

        await asyncio.sleep(0)
        self._run_id = run_id
        self._prepared = True

    async def warmup(self) -> None:
        """Run any target-side warmup needed before measurements begin."""
        if not self._prepared:
            msg = "prepare() must complete before warmup()"
            raise WarmupError(msg)
        await asyncio.sleep(0)

    async def measure(
        self,
        task: TaskSpec,
        iterations: int,
    ) -> AsyncIterator[InferenceResult]:
        """Yield one ordered result per inference iteration."""
        if not self._prepared:
            msg = "prepare() must complete before measure()"
            raise MeasureError(msg)
        if iterations <= 0:
            msg = "iterations must be positive"
            raise MeasureError(msg)

        for iter_id in range(iterations):
            await asyncio.sleep(0)
            yield InferenceResult(
                iter_id=iter_id,
                output={
                    "task_id": task.task_id,
                    "label": "mock",
                    "score": 1.0,
                },
                duration_us=self._mock_config.duration_us_base + iter_id,
                timestamp=dt.datetime.now(dt.UTC),
            )

    async def read_thermal(self) -> ThermalReading:
        """Return explicit thermal unavailability for targets without a sensor."""
        return ThermalReading(available=False)

    async def os_info(self) -> OSInfo:
        """Return target identity and firmware metadata."""
        if not self._prepared:
            msg = "prepare() must complete before os_info()"
            raise PrepareError(msg)
        return OSInfo(
            target_name=self.config.target_id,
            firmware_version=self._mock_config.firmware_version,
            additional={"example": "no-hardware"},
        )

    async def teardown(self) -> None:
        """Close target resources. This method must be safe to call twice."""
        await asyncio.sleep(0)
        self._prepared = False
        self._run_id = None
