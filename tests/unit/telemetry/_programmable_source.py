# SPDX-License-Identifier: Apache-2.0
"""Programmable telemetry sources for orchestrator tests."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from signal_bench.telemetry import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceDisconnectError, SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class ProgrammableMockConfig:
    """Configuration for an async source with deterministic failure hooks."""

    name: str = "programmable"
    sample_rate_hz: float = 20.0
    fail_on_start: bool = False
    fail_after_n_samples: int | None = None
    failure_exception: type[Exception] = SourceDisconnectError
    samples_to_emit: int | None = None
    sample_values: dict[str, float] | None = None
    stop_delay_s: float = 0.0
    stop_raises: bool = False


class ProgrammableMockSource(TelemetrySource):
    """Fully programmable source for telemetry orchestrator failure-mode tests."""

    source_name = "programmable"
    sample_rate_hz = 20.0

    def __init__(self, config: ProgrammableMockConfig | None = None) -> None:
        self.config = config or ProgrammableMockConfig()
        self.source_name = self.config.name
        self.sample_rate_hz = self.config.sample_rate_hz
        self.started = False
        self.stopped = False
        self.stop_calls = 0
        self.samples_emitted = 0

    @property
    def name(self) -> str:
        return self.config.name

    async def start(self) -> None:
        if self.config.fail_on_start:
            msg = f"{self.name} configured to fail on start"
            raise SourceStartError(msg)
        self.started = True
        self.stopped = False

    async def samples(self) -> AsyncIterator[TelemetrySample]:
        if not self.started:
            msg = f"{self.name} must be started before samples()"
            raise SourceStartError(msg)

        while not self.stopped:
            if (
                self.config.fail_after_n_samples is not None
                and self.samples_emitted >= self.config.fail_after_n_samples
            ):
                msg = f"{self.name} configured failure"
                raise self.config.failure_exception(msg)

            if (
                self.config.samples_to_emit is not None
                and self.samples_emitted >= self.config.samples_to_emit
            ):
                return

            self.samples_emitted += 1
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self.name,
                values=self.config.sample_values or {"voltage": 3.3, "current": 0.1, "power": 0.33},
            )
            await asyncio.sleep(1.0 / self.config.sample_rate_hz)

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.config.stop_delay_s:
            await asyncio.sleep(self.config.stop_delay_s)
        self.stopped = True
        if self.config.stop_raises:
            msg = f"{self.name} configured stop failure"
            raise RuntimeError(msg)
