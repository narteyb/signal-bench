# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from signal_bench.adapters.exceptions import MeasureError
from tests.fixtures.mock_serial import (
    MockSerialChannel,
    Scenario,
    consecutive_errors_scenario,
    disconnect_scenario,
    malformed_frame_scenario,
    single_error_scenario,
)
from tests.fixtures.test_helpers import (
    TestMCUAdapter,
    make_mcu_config,
    make_task,
    with_test_timeout,
)

if TYPE_CHECKING:
    from signal_bench.adapters.base import InferenceResult

pytestmark = pytest.mark.asyncio


async def _collect(adapter: TestMCUAdapter, *, iterations: int) -> list[InferenceResult]:
    return [result async for result in adapter.measure(make_task(), iterations)]


async def test_single_error_yields_error_result_continues(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(single_error_scenario(task_id="kws", error_at_iter=2))
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    results = await with_test_timeout(_collect(adapter, iterations=4))

    assert [result.iter_id for result in results] == [0, 1, 2, 3]
    assert results[2].output is None
    assert results[2].duration_us == 0
    assert results[2].error == "EINFER: iteration 2 failed"
    assert results[3].output == {"iter_id": 3}


async def test_three_consecutive_errors_raise_measure_error(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(consecutive_errors_scenario(error_count=3))
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))
    seen: list[InferenceResult] = []

    async def consume() -> None:
        async for result in adapter.measure(make_task(), 3):
            seen.append(result)  # noqa: PERF401 - keep partial results before expected raise

    with pytest.raises(MeasureError, match="3 consecutive errors"):
        await with_test_timeout(consume())

    assert len(seen) == 3
    assert [result.error for result in seen] == [
        "EINFER: failure 0",
        "EINFER: failure 1",
        "EINFER: failure 2",
    ]


async def test_serial_drop_mid_stream_raises_measure_error(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(disconnect_scenario(disconnect_at_iter=2))
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))
    seen: list[InferenceResult] = []

    async def consume() -> None:
        async for result in adapter.measure(make_task(), 3):
            seen.append(result)  # noqa: PERF401 - keep partial results before expected raise

    with pytest.raises(MeasureError, match="connection dropped"):
        await with_test_timeout(consume())

    assert [result.iter_id for result in seen] == [0, 1]


async def test_malformed_frame_handling(mock_serial_channel: MockSerialChannel) -> None:
    mock_serial_channel.use(malformed_frame_scenario())
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    with pytest.raises(MeasureError, match="frame parse failed"):
        await with_test_timeout(_collect(adapter, iterations=1))


async def test_done_total_iteration_mismatch_raises_measure_error(
    mock_serial_channel: MockSerialChannel,
) -> None:
    scenario = Scenario().expect_run("kws", 2).respond_with_done(total_iterations=1)
    mock_serial_channel.use(scenario)
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    with pytest.raises(MeasureError, match="did not match requested 2"):
        await with_test_timeout(_collect(adapter, iterations=2))


async def test_unexpected_frame_type_raises_measure_error(
    mock_serial_channel: MockSerialChannel,
) -> None:
    scenario = Scenario().expect_run("kws", 1).respond_with_raw(b"RUN kws 1\n")
    mock_serial_channel.use(scenario)
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    with pytest.raises(MeasureError, match="unexpected MCU frame"):
        await with_test_timeout(_collect(adapter, iterations=1))


async def test_measure_before_prepare_requires_writer() -> None:
    adapter = TestMCUAdapter(make_mcu_config())

    with pytest.raises(MeasureError, match="writer is not prepared"):
        await with_test_timeout(_collect(adapter, iterations=1))


async def test_read_frame_without_reader_requires_prepare() -> None:
    adapter = TestMCUAdapter(make_mcu_config())

    with pytest.raises(MeasureError, match="reader is not prepared"):
        await with_test_timeout(adapter._read_frame())
