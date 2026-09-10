# SPDX-License-Identifier: Apache-2.0
"""Mock adapter for pre-hardware task dispatch smoke tests."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from signal_bench.adapters.base import (
    Adapter,
    AdapterConfig,
    InferenceResult,
    OSInfo,
    ThermalReading,
)
from signal_bench.adapters.exceptions import MeasureError, PrepareError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from signal_bench.adapters.mcu.task import TaskSpec


@dataclass(frozen=True, slots=True)
class MockAdapterConfig(AdapterConfig):
    """Configuration for the synthetic benchmark target."""

    per_inference_us: int = 1234


class MockAdapter(Adapter):
    """Synthetic adapter that exercises orchestration without hardware."""

    name = "mock"

    def __init__(self: Self, config: MockAdapterConfig | None = None) -> None:
        """Create a mock adapter with default configuration when omitted."""
        super().__init__(config or MockAdapterConfig(target_id=self.name))
        self.config: MockAdapterConfig
        self._prepared_run_id: str | None = None

    async def prepare(self: Self, run_id: str) -> None:
        """Mark the mock target prepared for a run."""
        self._prepared_run_id = run_id

    async def warmup(self: Self) -> None:
        """No-op warmup for synthetic measurements."""
        if self._prepared_run_id is None:
            msg = "MockAdapter.warmup called before prepare"
            raise PrepareError(msg)

    async def measure(
        self: Self,
        task: TaskSpec,
        iterations: int,
    ) -> AsyncIterator[InferenceResult]:
        """Yield deterministic synthetic inference results."""
        if self._prepared_run_id is None:
            msg = "MockAdapter.measure called before prepare"
            raise MeasureError(msg)
        if iterations <= 0:
            msg = "iterations must be positive"
            raise MeasureError(msg)

        for iter_id in range(iterations):
            yield InferenceResult(
                iter_id=iter_id,
                output=_synthetic_output(task, iter_id),
                duration_us=self.config.per_inference_us,
                timestamp=dt.datetime.now(dt.UTC),
            )

    async def read_thermal(self: Self) -> ThermalReading:
        """Return unavailable thermal data for the mock target."""
        return ThermalReading(available=False)

    async def os_info(self: Self) -> OSInfo:
        """Return synthetic target identity."""
        return OSInfo(target_name=self.name, firmware_version="mock")

    async def teardown(self: Self) -> None:
        """Release synthetic target state."""
        self._prepared_run_id = None


def _synthetic_output(task: TaskSpec, iter_id: int) -> dict[str, Any]:
    shape = task.expected_output_shape or ()
    width = int(shape[-1]) if shape else 1
    selected = iter_id % max(width, 1)
    return {
        "task": task.task_id,
        "selected_index": selected,
        "output_hash": hashlib.sha256(f"{task.task_id}:{iter_id}".encode()).hexdigest()[:16],
    }
