# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from tests.fixtures.mock_serial import MockSerialChannel, Scenario, happy_path_scenario
from tests.fixtures.test_helpers import (
    TestMCUAdapter,
    make_mcu_config,
    make_task,
    with_test_timeout,
)

if TYPE_CHECKING:
    from signal_bench.adapters.base import InferenceResult

pytestmark = pytest.mark.asyncio


async def _collect(
    adapter: TestMCUAdapter,
    *,
    iterations: int,
    task_id: str = "kws",
) -> list[InferenceResult]:
    task = make_task(task_id)
    return [result async for result in adapter.measure(task, iterations)]


async def test_measure_yields_correct_inference_results(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(happy_path_scenario(task_id="kws", iterations=5))
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    results = await with_test_timeout(_collect(adapter, iterations=5))

    assert [result.iter_id for result in results] == [0, 1, 2, 3, 4]
    assert [result.output for result in results] == [{"iter_id": index} for index in range(5)]
    assert [result.duration_us for result in results] == [1200, 1201, 1202, 1203, 1204]
    assert all(result.error is None for result in results)
    assert all(result.timestamp.tzinfo is dt.UTC for result in results)


async def test_measure_terminates_on_done_frame(mock_serial_channel: MockSerialChannel) -> None:
    scenario = Scenario().expect_run("kws", 1).respond_with_done(total_iterations=1)
    mock_serial_channel.use(scenario)
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    results = await with_test_timeout(_collect(adapter, iterations=1))

    assert results == []


async def test_measure_writes_run_frame_to_writer(
    mock_serial_channel: MockSerialChannel,
) -> None:
    scenario = mock_serial_channel.use(happy_path_scenario(task_id="kws", iterations=3))
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    await with_test_timeout(_collect(adapter, iterations=3))

    assert scenario.writes == (b"RUN kws 3\n",)
    assert len(scenario.run_frames) == 1
    assert scenario.run_frames[0].task_id == "kws"
    assert scenario.run_frames[0].iterations == 3


async def test_measure_partial_frame_buffering(mock_serial_channel: MockSerialChannel) -> None:
    scenario = (
        Scenario()
        .expect_run("kws", 1)
        .respond_with_raw(b'RESULT 0 1200 {"iter')
        .respond_with_raw(b'_id":0}\n')
        .respond_with_done(total_iterations=1)
    )
    mock_serial_channel.use(scenario)
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    results = await with_test_timeout(_collect(adapter, iterations=1))

    assert len(results) == 1
    assert results[0].iter_id == 0
    assert results[0].output == {"iter_id": 0}
    assert results[0].duration_us == 1200
