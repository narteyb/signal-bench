# SPDX-License-Identifier: Apache-2.0
"""Shared async USB-serial implementation for MCU adapters."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
from abc import abstractmethod
from typing import TYPE_CHECKING, Self, TypeVar, cast

from signal_bench.adapters.base import Adapter, InferenceResult, OSInfo, ThermalReading
from signal_bench.adapters.exceptions import (
    ConfigurationError,
    MeasureError,
    PrepareError,
    TeardownError,
    WarmupError,
)
from signal_bench.adapters.mcu.frames import (
    DoneFrame,
    ErrFrame,
    Frame,
    FrameParser,
    MetadataFrame,
    ResultFrame,
    RunFrame,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from signal_bench.adapters.mcu.config import MCUAdapterConfig
    from signal_bench.adapters.mcu.task import TaskSpec

T = TypeVar("T")
MAX_CONSECUTIVE_ERRORS = 3


class MCUAdapterBase(Adapter):
    """Concrete base class for USB-CDC MCU target adapters.

    The class implements the six-method async adapter contract from AD-01 while
    leaving board-specific flashing and firmware identity to subclasses.
    """

    def __init__(self: Self, config: MCUAdapterConfig) -> None:
        """Create an MCU adapter from serial and firmware configuration.

        Args:
        ----
            config: MCU configuration containing target ID, serial port,
                baudrate, firmware paths, and lifecycle timeouts.

        Raises:
        ------
            ConfigurationError: Required serial settings are missing or invalid.

        """
        super().__init__(config)
        if not config.serial_port.strip():
            msg = "MCUAdapterConfig.serial_port must be set"
            raise ConfigurationError(msg)
        if config.baud_rate <= 0:
            msg = "MCUAdapterConfig.baud_rate must be positive"
            raise ConfigurationError(msg)

        self.config: MCUAdapterConfig = config
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._parser = FrameParser()
        self._run_id: str | None = None

    async def prepare(self: Self, run_id: str) -> None:
        """Prepare the MCU for a benchmark run.

        Opens the USB-CDC serial connection and, when configured, flashes
        firmware before opening the port. Repeated calls are idempotent once the
        serial connection is established.

        Args:
        ----
            run_id: Orchestrator-created run identifier for correlation only.

        Raises:
        ------
            PrepareError: Flashing or serial setup fails or times out.

        """
        await self._with_timeout(
            self._prepare(run_id),
            timeout_s=self.config.timeouts.prepare_s,
            error_type=PrepareError,
            messages=("MCU prepare timed out", "MCU prepare failed"),
        )

    async def warmup(self: Self) -> None:
        """Run the default MCU warmup step.

        The shared MCU base has no generic warmup protocol, so this is a no-op.
        Subclasses may override when a board-specific warmup sequence exists.

        Raises
        ------
            WarmupError: The no-op warmup is unexpectedly cancelled or times out.

        """
        await self._with_timeout(
            asyncio.sleep(0),
            timeout_s=self.config.timeouts.warmup_s,
            error_type=WarmupError,
            messages=("MCU warmup timed out", "MCU warmup failed"),
        )

    async def read_firmware_metadata(self: Self) -> dict[str, object]:
        """Query the prepared firmware before telemetry starts.

        A missing or malformed response is an error, so a session cannot be
        recorded with an assumed firmware identity.
        """
        if self._reader is None or self._writer is None:
            msg = "MCU must be prepared before META query"
            raise PrepareError(msg)
        self._writer.write(b"META\n")
        await self._writer.drain()
        frame = await self._with_timeout(
            self._read_frame(timeout_s=self.config.timeouts.prepare_s),
            timeout_s=self.config.timeouts.prepare_s,
            error_type=PrepareError,
            messages=("MCU META query timed out", "MCU META query failed"),
        )
        if not isinstance(frame, MetadataFrame):
            msg = f"expected META response, got {type(frame).__name__}"
            raise PrepareError(msg)
        return frame.values

    async def measure(
        self: Self,
        task: TaskSpec,
        iterations: int,
    ) -> AsyncIterator[InferenceResult]:
        """Run a task on the MCU and stream host-parsed inference results.

        Sends `RUN <task_id> <iterations>` to the serial device, then parses
        newline-delimited `RESULT`, `ERR`, and `DONE` frames until completion.
        Host-side timestamps are stamped when the frame is parsed.

        Args:
        ----
            task: Concrete task specification produced by orchestration.
            iterations: Number of measurement iterations requested.

        Yields:
        ------
            InferenceResult: One result per `RESULT` frame. A single `ERR`
            frame yields an `InferenceResult` with `error` populated.

        Raises:
        ------
            MeasureError: Serial I/O fails, parsing fails, the connection drops,
                or three consecutive `ERR` frames indicate bad device state.

        """
        if iterations <= 0:
            msg = "iterations must be positive"
            raise MeasureError(msg)

        await self._write_frame(RunFrame(task_id=task.task_id, iterations=iterations))

        consecutive_errors = 0
        inferred_error_iter = 0

        while True:
            frame = await self._read_frame()
            timestamp = dt.datetime.now(tz=dt.UTC)

            if isinstance(frame, ResultFrame):
                consecutive_errors = 0
                inferred_error_iter = frame.iter_id + 1
                yield InferenceResult(
                    iter_id=frame.iter_id,
                    output=frame.output,
                    duration_us=frame.duration_us,
                    timestamp=timestamp,
                )
                continue

            if isinstance(frame, ErrFrame):
                consecutive_errors += 1
                yield InferenceResult(
                    iter_id=inferred_error_iter,
                    output=None,
                    duration_us=0,
                    timestamp=timestamp,
                    error=f"{frame.code}: {frame.message}",
                )
                inferred_error_iter += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    msg = f"MCU reported {consecutive_errors} consecutive errors"
                    raise MeasureError(msg)
                continue

            if isinstance(frame, DoneFrame):
                if frame.total_iterations is not None and frame.total_iterations != iterations:
                    msg = (
                        "MCU DONE frame total_iterations "
                        f"{frame.total_iterations} did not match requested {iterations}"
                    )
                    raise MeasureError(msg)
                return

            msg = f"unexpected MCU frame during measurement: {type(frame).__name__}"
            raise MeasureError(msg)

    async def read_thermal(self: Self) -> ThermalReading:
        """Return default unavailable thermal data for sensorless MCU boards.

        Boards with readable on-die or board-level sensors should override this
        method. Sensorless boards can inherit this default.
        """
        return ThermalReading(available=False)

    async def os_info(self: Self) -> OSInfo:
        """Return target firmware identity reported by the concrete adapter.

        Calls the subclass-provided firmware version hook and wraps it in the
        shared `OSInfo` dataclass.

        Raises
        ------
            PrepareError: Firmware version reporting fails or times out.

        """
        version = await self._with_timeout(
            self._get_firmware_version(),
            timeout_s=self.config.timeouts.prepare_s,
            error_type=PrepareError,
            messages=(
                "MCU firmware version read timed out",
                "MCU firmware version read failed",
            ),
        )
        return OSInfo(target_name=self.config.target_id, firmware_version=version)

    async def teardown(self: Self) -> None:
        """Close the USB-CDC serial connection.

        Teardown is idempotent. Calling it before `prepare()` or after an
        earlier successful teardown is a no-op.

        Raises
        ------
            TeardownError: Serial cleanup fails or times out.

        """
        await self._with_timeout(
            self._close_serial(),
            timeout_s=self.config.timeouts.teardown_s,
            error_type=TeardownError,
            messages=("MCU teardown timed out", "MCU teardown failed"),
        )

    @abstractmethod
    async def _flash_firmware(self: Self) -> None:
        """Flash board-specific firmware before serial setup.

        Subclasses decide how to invoke their toolchain. The shared base only
        calls this hook when `config.flash_before_prepare` is true.
        """

    @abstractmethod
    async def _get_firmware_version(self: Self) -> str:
        """Return the prepared target firmware version string.

        Subclasses may query the serial protocol, inspect a compiled artifact,
        or return `"unknown"` when the firmware cannot report a version.
        """

    async def _prepare(self: Self, run_id: str) -> None:
        if self._writer is not None:
            self._run_id = run_id
            return

        if self.config.flash_before_prepare:
            await self._flash_firmware()

        self._reader, self._writer = await self._open_serial_connection()
        self._run_id = run_id

    async def _open_serial_connection(
        self: Self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        serial_asyncio = importlib.import_module("serial_asyncio")
        open_serial_connection = cast(
            "Callable[..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]",
            serial_asyncio.open_serial_connection,
        )
        return await open_serial_connection(
            url=self.config.serial_port,
            baudrate=self.config.baud_rate,
        )

    async def _write_frame(self: Self, frame: Frame) -> None:
        writer = self._require_writer()
        try:
            writer.write(frame.serialize().encode("ascii"))
            await asyncio.wait_for(
                writer.drain(),
                timeout=self.config.timeouts.measure_per_iteration_s,
            )
        except TimeoutError as error:
            msg = "MCU serial write timed out"
            raise MeasureError(msg) from error
        except (OSError, UnicodeEncodeError) as error:
            msg = "MCU serial write failed"
            raise MeasureError(msg) from error

    async def _read_frame(self: Self, *, timeout_s: float | None = None) -> Frame:
        reader = self._require_reader()
        try:
            line = await asyncio.wait_for(
                reader.readline(),
                timeout=timeout_s or self.config.timeouts.measure_per_iteration_s,
            )
        except TimeoutError as error:
            msg = "MCU serial read timed out"
            raise MeasureError(msg) from error
        except OSError as error:
            msg = "MCU serial read failed"
            raise MeasureError(msg) from error

        if not line:
            msg = "MCU serial connection dropped"
            raise MeasureError(msg)

        try:
            return self._parser.parse(line.decode("ascii"))
        except (UnicodeDecodeError, ValueError, TypeError) as error:
            msg = "MCU serial frame parse failed"
            raise MeasureError(msg) from error

    async def _close_serial(self: Self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        self._run_id = None

        if writer is None:
            return

        writer.close()
        await writer.wait_closed()

    def _require_reader(self: Self) -> asyncio.StreamReader:
        if self._reader is None:
            msg = "MCU serial reader is not prepared"
            raise MeasureError(msg)
        return self._reader

    def _require_writer(self: Self) -> asyncio.StreamWriter:
        if self._writer is None:
            msg = "MCU serial writer is not prepared"
            raise MeasureError(msg)
        return self._writer

    async def _with_timeout(
        self: Self,
        awaitable: Awaitable[T],
        *,
        timeout_s: float,
        error_type: type[PrepareError | WarmupError | TeardownError],
        messages: tuple[str, str],
    ) -> T:
        timeout_message, failure_message = messages
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout_s)
        except TimeoutError as error:
            raise error_type(timeout_message) from error
        except error_type:
            raise
        except Exception as error:
            raise error_type(failure_message) from error
