# SPDX-License-Identifier: Apache-2.0
"""Tests for the mock USB-CDC serial channel."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
import serial_asyncio  # type: ignore[import-untyped]

from signal_bench.adapters.mcu.frames import (
    DoneFrame,
    ErrFrame,
    FrameParser,
    ResultFrame,
    RunFrame,
)
from tests.fixtures.mock_serial import (
    MockSerialChannel,
    Scenario,
    consecutive_errors_scenario,
    disconnect_scenario,
    happy_path_scenario,
    malformed_frame_scenario,
    open_mock_serial_connection,
    single_error_scenario,
    timeout_scenario,
)

if TYPE_CHECKING:
    from collections.abc import Callable


pytestmark = pytest.mark.asyncio


async def test_scenario_builder_methods_produce_expected_device_bytes() -> None:
    scenario = (
        Scenario()
        .respond_with_result(iter_id=0, output={"label": "yes"}, duration_us=1234)
        .respond_with_error(code="EINFER", message="bad output")
        .respond_with_done(total_iterations=1)
        .respond_with_raw(b"GARBAGE\n")
    )

    assert scenario.device_bytes == (
        ResultFrame(iter_id=0, output={"label": "yes"}, duration_us=1234)
        .serialize()
        .encode("ascii")
        + ErrFrame(code="EINFER", message="bad output").serialize().encode("ascii")
        + DoneFrame(total_iterations=1).serialize().encode("ascii")
        + b"GARBAGE\n"
    )


async def test_expect_run_strict_validation_passes_on_match() -> None:
    scenario = Scenario().expect_run(task_id="kws", iterations=5).respond_with_done()
    reader, writer = await open_mock_serial_connection(scenario)

    writer.write(RunFrame(task_id="kws", iterations=5).serialize().encode("ascii"))
    await writer.drain()
    await scenario.wait_until_idle()

    assert scenario.run_frames == (RunFrame(task_id="kws", iterations=5),)
    assert await reader.readline() == b"DONE\n"


async def test_expect_run_strict_validation_raises_on_mismatch() -> None:
    scenario = Scenario().expect_run(task_id="kws", iterations=5)
    _reader, writer = await open_mock_serial_connection(scenario)

    with pytest.raises(AssertionError, match="expected RUN task_id"):
        writer.write(RunFrame(task_id="ic", iterations=5).serialize().encode("ascii"))


async def test_expect_any_run_accepts_any_valid_run_frame() -> None:
    scenario = Scenario().expect_any_run().respond_with_done()
    reader, writer = await open_mock_serial_connection(scenario)

    writer.write(RunFrame(task_id="ic", iterations=10).serialize().encode("ascii"))
    await writer.drain()
    await scenario.wait_until_idle()

    assert scenario.run_frames == (RunFrame(task_id="ic", iterations=10),)
    assert await reader.readline() == b"DONE\n"


@pytest.mark.parametrize(
    ("factory", "run_frame", "expected_tags"),
    [
        (
            happy_path_scenario,
            RunFrame(task_id="kws", iterations=5),
            ["RESULT", "RESULT", "RESULT", "RESULT", "RESULT", "DONE"],
        ),
        (
            single_error_scenario,
            RunFrame(task_id="kws", iterations=4),
            ["RESULT", "RESULT", "ERR", "RESULT", "DONE"],
        ),
        (
            consecutive_errors_scenario,
            RunFrame(task_id="ad", iterations=3),
            ["ERR", "ERR", "ERR"],
        ),
        (
            disconnect_scenario,
            RunFrame(task_id="ad", iterations=3),
            ["RESULT", "RESULT"],
        ),
        (
            malformed_frame_scenario,
            RunFrame(task_id="kws", iterations=1),
            ["NOT_A_FRAME"],
        ),
    ],
)
async def test_common_scenario_factories_produce_expected_streams(
    factory: Callable[[], Scenario],
    run_frame: RunFrame,
    expected_tags: list[str],
) -> None:
    scenario = factory()
    reader, writer = await open_mock_serial_connection(scenario)

    writer.write(run_frame.serialize().encode("ascii"))
    await writer.drain()
    await scenario.wait_until_idle()

    lines = await _read_available_lines(reader)
    assert [_line_tag(line) for line in lines] == expected_tags


async def test_timeout_scenario_honors_delay() -> None:
    scenario = timeout_scenario(delay_s=0.02)
    reader, writer = await open_mock_serial_connection(scenario)

    start = time.monotonic()
    writer.write(RunFrame(task_id="kws", iterations=1).serialize().encode("ascii"))
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.02
    assert _line_tag(line) == "RESULT"


async def test_disconnect_closes_reader() -> None:
    scenario = Scenario().expect_any_run().disconnect()
    reader, writer = await open_mock_serial_connection(scenario)

    writer.write(RunFrame(task_id="kws", iterations=1).serialize().encode("ascii"))
    await writer.drain()
    await scenario.wait_until_idle()

    assert await reader.readline() == b""


async def test_malformed_frame_scenario_emits_ungrammatical_bytes() -> None:
    scenario = malformed_frame_scenario()
    reader, writer = await open_mock_serial_connection(scenario)

    writer.write(RunFrame(task_id="kws", iterations=1).serialize().encode("ascii"))
    await writer.drain()
    await scenario.wait_until_idle()

    line = await reader.readline()
    assert line == b"NOT_A_FRAME\n"
    with pytest.raises(ValueError, match="unknown MCU frame tag"):
        FrameParser().parse(line.decode("ascii"))


async def test_mock_serial_channel_fixture_patches_serial_asyncio(
    mock_serial_channel: MockSerialChannel,
) -> None:
    scenario = mock_serial_channel.use(Scenario().expect_any_run().respond_with_done())
    reader, writer = await serial_asyncio.open_serial_connection(url="mock://mcu", baudrate=115200)

    writer.write(RunFrame(task_id="kws", iterations=1).serialize().encode("ascii"))
    await writer.drain()
    await scenario.wait_until_idle()

    assert mock_serial_channel.calls == [
        {"args": (), "kwargs": {"url": "mock://mcu", "baudrate": 115200}},
    ]
    assert await reader.readline() == b"DONE\n"


async def _read_available_lines(reader: asyncio.StreamReader) -> list[bytes]:
    lines: list[bytes] = []
    while True:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=0.001)
        except TimeoutError:
            return lines
        if not line:
            return lines
        lines.append(line)


def _line_tag(line: bytes) -> str:
    return line.decode("ascii").strip().split(maxsplit=1)[0]
