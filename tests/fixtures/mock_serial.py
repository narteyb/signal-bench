# SPDX-License-Identifier: Apache-2.0
"""In-memory USB-CDC serial mock for MCU adapter tests.

The mock replaces `serial_asyncio.open_serial_connection()` with a pure-Python
async channel that returns the same `(asyncio.StreamReader, asyncio.StreamWriter)`
shape used by `MCUAdapterBase`. Tests script device-side behavior with
`Scenario` and then assert the host emitted the expected `RUN` frame.

Usage example:

```python
scenario = (
    Scenario()
    .expect_run(task_id="kws", iterations=5)
    .respond_with_results(count=5, base_duration_us=1200)
    .respond_with_done()
)
reader, writer = await open_mock_serial_connection(scenario)
```

This lives under `tests/` for v0.1. If downstream adapter authors need the same
tooling, promote it to `signal_bench.testing.mock_serial` in v0.2.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from collections.abc import Iterable

from signal_bench.adapters.mcu.frames import DoneFrame, ErrFrame, FrameParser, ResultFrame, RunFrame


@dataclass(frozen=True, slots=True)
class _ExpectedRun:
    task_id: str | None
    iterations: int | None


@dataclass(frozen=True, slots=True)
class _EmitBytes:
    payload: bytes


@dataclass(frozen=True, slots=True)
class _Delay:
    seconds: float


@dataclass(frozen=True, slots=True)
class _Disconnect:
    pass


_Action = _ExpectedRun | _EmitBytes | _Delay | _Disconnect


class Scenario:
    """Linear script for a mock MCU serial session."""

    def __init__(self: Self) -> None:
        """Create an empty scenario."""
        self._actions: list[_Action] = []
        self._reader: asyncio.StreamReader | None = None
        self._transport: MockSerialTransport | None = None
        self._position = 0
        self._host_buffer = bytearray()
        self._writes: list[bytes] = []
        self._run_frames: list[RunFrame] = []
        self._advance_task: asyncio.Task[None] | None = None
        self._parser = FrameParser()

    @property
    def writes(self: Self) -> tuple[bytes, ...]:
        """Bytes written by the host."""
        return tuple(self._writes)

    @property
    def run_frames(self: Self) -> tuple[RunFrame, ...]:
        """Parsed `RUN` frames written by the host."""
        return tuple(self._run_frames)

    @property
    def device_bytes(self: Self) -> bytes:
        """Device-side bytes scripted by emit actions."""
        chunks = [action.payload for action in self._actions if isinstance(action, _EmitBytes)]
        return b"".join(chunks)

    def expect_run(self: Self, task_id: str, iterations: int) -> Self:
        """Require the host to write exactly `RUN <task_id> <iterations>`."""
        self._actions.append(_ExpectedRun(task_id=task_id, iterations=iterations))
        return self

    def expect_any_run(self: Self) -> Self:
        """Require the host to write any syntactically valid `RUN` frame."""
        self._actions.append(_ExpectedRun(task_id=None, iterations=None))
        return self

    def respond_with_result(self: Self, iter_id: int, output: object, duration_us: int) -> Self:
        """Emit one device-side `RESULT` frame."""
        frame = ResultFrame(iter_id=iter_id, output=output, duration_us=duration_us)
        self._actions.append(_EmitBytes(frame.serialize().encode("ascii")))
        return self

    def respond_with_results(self: Self, count: int, base_duration_us: int = 1_200) -> Self:
        """Emit `count` sequential `RESULT` frames."""
        for iter_id in range(count):
            self.respond_with_result(
                iter_id=iter_id,
                output={"iter_id": iter_id},
                duration_us=base_duration_us + iter_id,
            )
        return self

    def respond_with_error(self: Self, code: str, message: str) -> Self:
        """Emit one device-side `ERR` frame."""
        frame = ErrFrame(code=code, message=message)
        self._actions.append(_EmitBytes(frame.serialize().encode("ascii")))
        return self

    def respond_with_done(self: Self, total_iterations: int | None = None) -> Self:
        """Emit a device-side `DONE` frame."""
        self._actions.append(
            _EmitBytes(DoneFrame(total_iterations=total_iterations).serialize().encode("ascii"))
        )
        return self

    def respond_with_raw(self: Self, payload: bytes) -> Self:
        """Emit arbitrary raw bytes from the device."""
        self._actions.append(_EmitBytes(payload))
        return self

    def delay(self: Self, seconds: float) -> Self:
        """Pause device-side emission for `seconds`."""
        if seconds < 0:
            msg = "delay seconds must be non-negative"
            raise ValueError(msg)
        self._actions.append(_Delay(seconds=seconds))
        return self

    def disconnect(self: Self) -> Self:
        """Simulate a serial drop by closing the reader with EOF."""
        self._actions.append(_Disconnect())
        return self

    async def wait_until_idle(self: Self) -> None:
        """Wait for any currently scheduled device-side action to finish."""
        task = self._advance_task
        if task is not None:
            await task

    def attach(
        self: Self,
        reader: asyncio.StreamReader,
        transport: MockSerialTransport,
    ) -> None:
        """Attach the scenario to an opened mock serial channel."""
        if self._reader is not None:
            msg = "scenario is already attached to a mock serial channel"
            raise RuntimeError(msg)
        self._reader = reader
        self._transport = transport
        self._schedule_advance()

    def record_host_write(self: Self, data: bytes) -> None:
        """Capture and validate bytes written by the host."""
        self._writes.append(data)
        self._host_buffer.extend(data)

        while b"\n" in self._host_buffer:
            line, _, remainder = self._host_buffer.partition(b"\n")
            self._host_buffer = bytearray(remainder)
            self._validate_host_line(line.decode("ascii"))

    def _validate_host_line(self: Self, line: str) -> None:
        if self._position >= len(self._actions):
            return

        action = self._actions[self._position]
        if not isinstance(action, _ExpectedRun):
            return

        frame = self._parser.parse(line)
        msg = f"expected RUN frame, got {type(frame).__name__}"
        assert isinstance(frame, RunFrame), msg
        if action.task_id is not None and frame.task_id != action.task_id:
            msg = f"expected RUN task_id {action.task_id!r}, got {frame.task_id!r}"
            raise AssertionError(msg)
        if action.iterations is not None and frame.iterations != action.iterations:
            msg = f"expected RUN iterations {action.iterations}, got {frame.iterations}"
            raise AssertionError(msg)

        self._run_frames.append(frame)
        self._position += 1
        self._schedule_advance()

    def _schedule_advance(self: Self) -> None:
        if self._advance_task is not None and not self._advance_task.done():
            return
        self._advance_task = asyncio.create_task(self._advance())

    async def _advance(self: Self) -> None:
        reader = self._require_reader()

        while self._position < len(self._actions):
            action = self._actions[self._position]
            if isinstance(action, _ExpectedRun):
                return
            if isinstance(action, _EmitBytes):
                reader.feed_data(action.payload)
            elif isinstance(action, _Delay):
                await asyncio.sleep(action.seconds)
            elif isinstance(action, _Disconnect):
                reader.feed_eof()
                transport = self._transport
                if transport is not None:
                    transport.mark_device_disconnected()
            self._position += 1

    def _require_reader(self: Self) -> asyncio.StreamReader:
        if self._reader is None:
            msg = "scenario is not attached to a mock serial channel"
            raise RuntimeError(msg)
        return self._reader


class MockSerialTransport(asyncio.Transport):
    """Minimal transport that captures host writes for a `StreamWriter`."""

    def __init__(
        self: Self,
        scenario: Scenario,
        protocol: asyncio.StreamReaderProtocol,
    ) -> None:
        """Create a transport connected to `scenario`."""
        super().__init__()
        self._scenario = scenario
        self._protocol = protocol
        self._closing = False
        self._device_disconnected = False

    def write(self: Self, data: bytes | bytearray | memoryview) -> None:
        """Capture host writes and validate scripted expectations."""
        if self._closing:
            msg = "cannot write to closed mock serial transport"
            raise RuntimeError(msg)
        self._scenario.record_host_write(bytes(data))

    def writelines(
        self: Self,
        list_of_data: Iterable[bytes | bytearray | memoryview[Any]],
    ) -> None:
        """Capture a sequence of host writes."""
        for data in list_of_data:
            self.write(data)

    def close(self: Self) -> None:
        """Close the host side of the mock transport."""
        if self._closing:
            return
        self._closing = True
        self._protocol.connection_lost(None)

    def is_closing(self: Self) -> bool:
        """Return whether the host-side transport has been closed."""
        return self._closing

    def can_write_eof(self: Self) -> bool:
        """Report EOF support to satisfy `asyncio` transport shape."""
        return True

    def write_eof(self: Self) -> None:
        """Mark the device as disconnected."""
        self.mark_device_disconnected()

    def get_write_buffer_size(self: Self) -> int:
        """Return zero because writes are captured synchronously."""
        return 0

    def set_write_buffer_limits(
        self: Self,
        high: int | None = None,
        low: int | None = None,
    ) -> None:
        """Accept write buffer limit calls for StreamWriter compatibility."""

    def get_extra_info(self: Self, name: str, default: Any = None) -> Any:
        """Return mock serial metadata."""
        if name == "serial":
            return self
        if name == "peername":
            return "mock-serial"
        return default

    def mark_device_disconnected(self: Self) -> None:
        """Mark device-side EOF without closing the host writer."""
        self._device_disconnected = True

    @property
    def device_disconnected(self: Self) -> bool:
        """Return whether the scenario simulated a device disconnect."""
        return self._device_disconnected


class MockSerialChannel:
    """Fixture helper that patches `serial_asyncio` to one active scenario."""

    def __init__(self: Self) -> None:
        """Create an empty channel helper."""
        self.scenario: Scenario | None = None
        self.calls: list[dict[str, object]] = []

    def use(self: Self, scenario: Scenario) -> Scenario:
        """Set the scenario returned by the next mocked serial open call."""
        self.scenario = scenario
        return scenario

    async def open(
        self: Self,
        *args: object,
        **kwargs: object,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Replace `serial_asyncio.open_serial_connection`."""
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.scenario is None:
            msg = "mock_serial_channel.use(scenario) must be called before opening serial"
            raise AssertionError(msg)
        return await open_mock_serial_connection(self.scenario)


async def open_mock_serial_connection(
    scenario: Scenario,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open an in-memory serial connection for `scenario`.

    The return value mirrors `serial_asyncio.open_serial_connection()`.
    """
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    transport = MockSerialTransport(scenario=scenario, protocol=protocol)
    protocol.connection_made(transport)
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    scenario.attach(reader, transport)
    return reader, writer


def happy_path_scenario(task_id: str = "kws", iterations: int = 5) -> Scenario:
    """Return a successful RUN/RESULT*/DONE scenario."""
    return (
        Scenario()
        .expect_run(task_id=task_id, iterations=iterations)
        .respond_with_results(count=iterations)
        .respond_with_done(total_iterations=iterations)
    )


def single_error_scenario(task_id: str = "kws", error_at_iter: int = 2) -> Scenario:
    """Return a scenario with one per-inference error followed by success."""
    scenario = Scenario().expect_run(task_id=task_id, iterations=error_at_iter + 2)
    for iter_id in range(error_at_iter):
        scenario.respond_with_result(
            iter_id=iter_id,
            output={"iter_id": iter_id},
            duration_us=1_200 + iter_id,
        )
    return (
        scenario.respond_with_error(code="EINFER", message=f"iteration {error_at_iter} failed")
        .respond_with_result(
            iter_id=error_at_iter + 1,
            output={"iter_id": error_at_iter + 1},
            duration_us=1_200 + error_at_iter + 1,
        )
        .respond_with_done(total_iterations=error_at_iter + 2)
    )


def consecutive_errors_scenario(error_count: int = 3) -> Scenario:
    """Return a scenario that emits consecutive `ERR` frames."""
    scenario = Scenario().expect_any_run()
    for index in range(error_count):
        scenario.respond_with_error(code="EINFER", message=f"failure {index}")
    return scenario


def timeout_scenario(delay_s: float = 60.0) -> Scenario:
    """Return a scenario that delays before emitting a successful result."""
    return (
        Scenario()
        .expect_any_run()
        .delay(delay_s)
        .respond_with_result(iter_id=0, output={"iter_id": 0}, duration_us=1_200)
        .respond_with_done(total_iterations=1)
    )


def disconnect_scenario(disconnect_at_iter: int = 2) -> Scenario:
    """Return a scenario that disconnects after `disconnect_at_iter` results."""
    scenario = Scenario().expect_any_run()
    for iter_id in range(disconnect_at_iter):
        scenario.respond_with_result(
            iter_id=iter_id,
            output={"iter_id": iter_id},
            duration_us=1_200 + iter_id,
        )
    return scenario.disconnect()


def malformed_frame_scenario() -> Scenario:
    """Return a scenario that emits bytes rejected by `FrameParser`."""
    return Scenario().expect_any_run().respond_with_raw(b"NOT_A_FRAME\n")
