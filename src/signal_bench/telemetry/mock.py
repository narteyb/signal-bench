# SPDX-License-Identifier: Apache-2.0
"""Deterministic mock telemetry source for testing and CLI smoke tests."""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import time
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource


class MockTelemetrySource(TelemetrySource):
    """Synthetic telemetry source with deterministic sample values."""

    source_name = "mock"
    sample_rate_hz = 10.0

    def __init__(
        self: Self,
        rate_hz: float = 10.0,
        metrics: tuple[str, ...] = ("voltage_v", "current_ma", "power_w"),
        fail_after: float | None = None,
    ) -> None:
        """Create a mock source.

        Args:
        ----
            rate_hz: Samples generated per second.
            metrics: Metric names emitted at each sample tick.
            fail_after: If set, sample() raises after this many seconds.

        """
        self.sample_rate_hz = rate_hz
        self._metrics = metrics
        self._fail_after = fail_after
        self._opened_at: float | None = None
        self._last_sample = 0.0
        self._is_open = False

    def is_available(self: Self) -> bool:
        """Return True; mock telemetry has no external dependency."""
        return True

    @property
    def name(self: Self) -> str:
        """Return the stable async telemetry source name."""
        return self.source_name

    async def start(self: Self) -> None:
        """Start async mock sample generation."""
        self.open()

    async def stop(self: Self) -> None:
        """Stop async mock sample generation."""
        self.close()

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield deterministic samples until stopped."""
        while self._is_open:
            for sample in self.sample():
                yield sample
            await asyncio.sleep(1.0 / self.sample_rate_hz)

    def open(self: Self) -> None:
        """Start mock sample generation."""
        self._opened_at = time.monotonic()
        self._last_sample = self._opened_at
        self._is_open = True

    def close(self: Self) -> None:
        """Stop mock sample generation."""
        self._is_open = False

    def sample(self: Self) -> list[TelemetrySample]:
        """Return deterministic samples produced since the last call."""
        if not self._is_open or self._opened_at is None:
            return []

        now = time.monotonic()
        elapsed = now - self._opened_at
        if self._fail_after is not None and elapsed > self._fail_after:
            msg = f"mock source configured to fail after {self._fail_after}s"
            raise RuntimeError(msg)

        interval = 1.0 / self.sample_rate_hz
        samples: list[TelemetrySample] = []
        sample_time = self._last_sample + interval

        while sample_time <= now:
            timestamp = dt.datetime.fromtimestamp(sample_time, tz=dt.UTC)
            phase = sample_time - self._opened_at
            for metric in self._metrics:
                base = {"voltage_v": 5.0, "current_ma": 200.0, "power_w": 1.0}.get(
                    metric,
                    1.0,
                )
                value = base + (0.1 * math.sin(phase * 0.5))
                samples.append(
                    TelemetrySample(
                        timestamp=timestamp,
                        source=self.source_name,
                        metric=metric,
                        value=value,
                    ),
                )
            sample_time += interval

        self._last_sample = sample_time - interval
        return samples
