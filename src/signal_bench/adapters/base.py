# SPDX-License-Identifier: Apache-2.0
"""Abstract adapter contract for signal-bench target hardware."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from signal_bench.adapters.mcu.task import TaskSpec


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """One inference result yielded by an adapter during measurement."""

    iter_id: int
    output: Any
    duration_us: int
    timestamp: dt.datetime
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ThermalReading:
    """Thermal state reported by a prepared target."""

    available: bool
    temperature_c: float | None = None
    sensor: str | None = None
    timestamp: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class OSInfo:
    """Target operating system or firmware identity."""

    target_name: str
    firmware_version: str
    additional: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TimeoutConfig:
    """Timeouts used by orchestrators around adapter lifecycle calls."""

    prepare_s: float = 30.0
    warmup_s: float = 60.0
    measure_per_iteration_s: float = 5.0
    teardown_s: float = 15.0


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    """Base configuration shared by all signal-bench adapters."""

    target_id: str
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)


class Adapter(ABC):
    """Abstract interface implemented by every signal-bench target adapter.

    Canonical lifecycle:
    `__init__(config) -> prepare(run_id) -> warmup() -> measure(task, iterations) -> teardown()`.

    `os_info()` and `read_thermal()` may be called after `prepare()` returns
    successfully. `measure()` is called exactly once per prepare/teardown cycle.
    `prepare()` and `teardown()` must be idempotent; `measure()` is not
    idempotent because it consumes target state and emits ordered results.
    """

    def __init__(self: Self, config: AdapterConfig) -> None:
        """Create an adapter from validated configuration.

        Args:
        ----
            config: Base adapter configuration, including target identifier and
                lifecycle timeout values. Concrete adapters may require a
                subclass of `AdapterConfig`.

        Raises:
        ------
            ConfigurationError: Concrete adapters should raise this when config
                values are internally inconsistent or unusable.

        Lifecycle:
            Construction happens before `prepare()`. Implementations should not
            perform slow target I/O here; reserve hardware setup for `prepare()`.
        """
        self.config = config

    @abstractmethod
    async def prepare(self: Self, run_id: str) -> None:
        """Prepare target hardware for a benchmark run.

        Args:
        ----
            run_id: Orchestrator-created run identifier. The adapter may use it
                for hardware-side logging or correlation, but must not write to
                the `runs` table.

        Returns:
        -------
            None. Successful return means the target is ready for `warmup()`.

        Raises:
        ------
            PrepareError: The target could not be initialized, flashed,
                connected, or otherwise prepared for the run.

        Lifecycle:
            First async lifecycle call after construction. Must be idempotent:
            calling `prepare()` more than once for the same run should not create
            duplicate target-side state or corrupt the connection.
        """

    @abstractmethod
    async def warmup(self: Self) -> None:
        """Warm the target before persisted measurements begin.

        Returns
        -------
            None. Warmup iterations are discarded by contract and are not yielded
            from `measure()`.

        Raises
        ------
            WarmupError: Warmup failed or the target did not reach a valid
                measurement state.

        Lifecycle:
            Called after `prepare()` and before `measure()`. Implementations
            should use `config.timeouts.warmup_s` when bounding target I/O.
        """

    @abstractmethod
    async def measure(
        self: Self, task: TaskSpec, iterations: int
    ) -> AsyncIterator[InferenceResult]:
        """Run benchmark measurements and stream per-inference results.

        Args:
        ----
            task: Concrete task payload containing the task identifier, model
                path, input data path, expected output shape, and task-specific
                metadata.
            iterations: Number of measurement iterations to run and yield.

        Yields:
        ------
            `InferenceResult` objects in measurement order. Each yielded result
            represents exactly one inference attempt.

        Raises:
        ------
            MeasureError: Measurement cannot continue. Results yielded before
                the exception remain valid for orchestrator policy decisions.

        Lifecycle:
            Called after `warmup()` exactly once per `prepare()`/`teardown()`
            cycle. Not idempotent: repeated calls would duplicate measurements
            and complicate target state.
        """
        if False:
            yield InferenceResult(0, None, 0, dt.datetime.now(tz=dt.UTC))

    @abstractmethod
    async def read_thermal(self: Self) -> ThermalReading:
        """Read target thermal state.

        Returns
        -------
            A `ThermalReading`. Targets without a readable thermal sensor should
            return `ThermalReading(available=False)` from concrete base classes
            or raise `ThermalUnavailable` when the read path itself fails.

        Raises
        ------
            ThermalUnavailable: Thermal data is expected for the adapter but
                cannot be read from the target.

        Lifecycle:
            Callable any time after `prepare()` returns successfully, including
            before, during, or after measurement while the target is still
            prepared.
        """

    @abstractmethod
    async def os_info(self: Self) -> OSInfo:
        """Return target operating system or firmware metadata.

        Returns
        -------
            `OSInfo` with required `target_name` and `firmware_version` fields.
            Use `"unknown"` for firmware version when a target cannot report it.

        Raises
        ------
            PrepareError: Metadata cannot be read because the target is not
                prepared or reachable.

        Lifecycle:
            Callable any time after `prepare()` returns successfully. The
            orchestrator records this data on run or target metadata rather than
            allowing adapters to write directly to the database.
        """

    @abstractmethod
    async def teardown(self: Self) -> None:
        """Release target resources after measurement.

        Returns
        -------
            None. Successful return means target-side resources have been
            released as far as the adapter can verify.

        Raises
        ------
            TeardownError: Cleanup failed. Orchestrators should record this
                without masking a prior prepare, warmup, or measure failure.

        Lifecycle:
            Final lifecycle call. Must be idempotent: repeated teardown calls
            should do no harm and should not require `prepare()` to still be
            active.
        """
