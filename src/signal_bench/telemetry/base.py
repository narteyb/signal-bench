# SPDX-License-Identifier: Apache-2.0
"""Telemetry source contracts and shared types."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import nan
from numbers import Real
from typing import TYPE_CHECKING, Self

from signal_bench.telemetry.exceptions import TelemetryUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

__all__ = [
    "OrchestratorConfig",
    "TelemetrySample",
    "TelemetrySource",
    "TelemetryUnavailableError",
]


@dataclass(frozen=True, slots=True, init=False)
class TelemetrySample:
    """One telemetry sample captured by one source at one moment.

    New async sources populate ``source_name`` and ``values``. ``values`` maps
    source-specific metric names to numeric values, for example
    ``{"voltage_v": 5.01, "current_ma": 200.4}``.

    The constructor also accepts the M2a scalar shape
    ``source`` / ``metric`` / ``value`` for compatibility with the existing
    synchronous ``TelemetryCollector``. Those scalar fields remain available as
    read-only properties when exactly one value is present.
    """

    timestamp: datetime
    source_name: str
    values: dict[str, float]
    unit_hints: dict[str, str] = field(default_factory=dict)
    source: str = field(init=False)
    metric: str = field(init=False)
    value: float = field(init=False)

    def __init__(  # noqa: PLR0913 - accepts old scalar and new grouped sample shapes.
        self: Self,
        timestamp: datetime,
        source_name: str | None = None,
        values: Mapping[str, float] | str | None = None,
        unit_hints: Mapping[str, str] | float | None = None,
        *,
        source: str | None = None,
        metric: str | None = None,
        value: float | None = None,
    ) -> None:
        """Create a telemetry sample.

        Args:
        ----
            timestamp: UTC timestamp from the source.
            source_name: Stable telemetry source name.
            values: Mapping of metric names to values. A string here is treated
                as the legacy positional ``metric`` argument.
            unit_hints: Optional mapping of metric names to display units. A
                numeric value here is treated as the legacy positional
                ``value`` argument.
            source: Legacy keyword alias for ``source_name``.
            metric: Legacy scalar metric name.
            value: Legacy scalar metric value.

        """
        resolved_source = source_name if source_name is not None else source
        resolved_values: Mapping[str, float] | None
        resolved_unit_hints: Mapping[str, str] | None

        if isinstance(values, str) and isinstance(unit_hints, Real):
            metric = values
            value = float(unit_hints)
            resolved_values = None
            resolved_unit_hints = None
        else:
            resolved_values = values if not isinstance(values, str) else None
            resolved_unit_hints = unit_hints if isinstance(unit_hints, Mapping) else None

        if resolved_source is None:
            msg = "TelemetrySample requires source_name or source"
            raise TypeError(msg)

        if resolved_values is None:
            if metric is None or value is None:
                msg = "TelemetrySample requires values or metric/value"
                raise TypeError(msg)
            resolved_values = {metric: float(value)}

        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "source_name", resolved_source)
        object.__setattr__(
            self,
            "values",
            {name: float(measurement) for name, measurement in resolved_values.items()},
        )
        object.__setattr__(self, "unit_hints", dict(resolved_unit_hints or {}))
        object.__setattr__(self, "source", resolved_source)
        if len(self.values) == 1:
            metric_name, metric_value = next(iter(self.values.items()))
            object.__setattr__(self, "metric", metric_name)
            object.__setattr__(self, "value", metric_value)
        else:
            object.__setattr__(self, "metric", "")
            object.__setattr__(self, "value", nan)

    def __hash__(self: Self) -> int:
        """Return a stable hash despite dict-backed values."""
        return hash(
            (
                self.timestamp,
                self.source_name,
                tuple(sorted(self.values.items())),
                tuple(sorted(self.unit_hints.items())),
            ),
        )


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    """Runtime knobs for the async telemetry orchestrator.

    T7.2 uses these values for queue sizing, batched database writes, and
    graceful shutdown timing.
    """

    queue_maxsize: int = 1_024
    batch_size: int = 200
    flush_interval_s: float = 0.5
    shutdown_timeout_s: float = 5.0


class TelemetrySource(ABC):
    """Async telemetry source contract for the T7 orchestrator.

    Implementations own their hardware or transport connection. They do not
    write to the database and they do not update ``runs`` rows; the orchestrator
    owns persistence and partial-run policy.

    The legacy synchronous ``is_available()``, ``open()``, ``sample()``, and
    ``close()`` methods remain as compatibility hooks for the M2a
    ``TelemetryCollector`` until T7.2 replaces the active data path.
    """

    source_name: str
    sample_rate_hz: float
    partial_coverage_threshold: float | None = None

    @property
    @abstractmethod
    def name(self: Self) -> str:
        """Stable source identifier, for example ``"fnb58"`` or ``"ina219_mock"``."""

    @abstractmethod
    async def start(self: Self) -> None:
        """Begin sample emission.

        Raises
        ------
            SourceStartError: The source cannot connect or initialize.

        Lifecycle:
            Called once by the orchestrator before ``samples()`` is consumed.
            Implementations must make repeated calls harmless.

        """

    @abstractmethod
    def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield samples until stopped or an unrecoverable source error occurs.

        Raises
        ------
            SourceDisconnectError: The source disconnects mid-run.
            SourceDataError: The source receives or produces malformed data.

        Lifecycle:
            Called after ``start()`` succeeds. The iterator is not re-entered
            after ``stop()``.

        """

    @abstractmethod
    async def stop(self: Self) -> None:
        """Halt sample emission and release resources.

        Lifecycle:
            Called during orchestrator shutdown. Implementations must make
            repeated calls harmless.
        """

    def is_available(self: Self) -> bool:
        """Return True if the source's library and likely hardware are usable.

        Compatibility hook for the existing synchronous collector and CLI.
        Async sources may override this for cheap availability checks.
        """
        return True

    def open(self: Self) -> None:
        """Connect or initialize the source.

        Compatibility hook for the existing synchronous collector.
        """
        msg = f"{type(self).__name__} does not implement the legacy open() hook"
        raise NotImplementedError(msg)

    def close(self: Self) -> None:
        """Disconnect and clean up.

        Compatibility hook for the existing synchronous collector.
        """
        msg = f"{type(self).__name__} does not implement the legacy close() hook"
        raise NotImplementedError(msg)

    def sample(self: Self) -> list[TelemetrySample]:
        """Return zero or more samples captured at this instant.

        Compatibility hook for the existing synchronous collector.
        """
        msg = f"{type(self).__name__} does not implement the legacy sample() hook"
        raise NotImplementedError(msg)

    async def sleep_for_sample_interval(self: Self) -> None:
        """Sleep for one source sample interval.

        Shared helper for simple polling sources.
        """
        await asyncio.sleep(1.0 / self.sample_rate_hz)
