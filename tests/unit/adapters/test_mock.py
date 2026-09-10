# SPDX-License-Identifier: Apache-2.0
import pytest

from signal_bench.adapters import MockAdapter
from signal_bench.adapters.exceptions import MeasureError, PrepareError
from signal_bench.tasks import get_task


@pytest.mark.asyncio
async def test_mock_adapter_yields_deterministic_results() -> None:
    adapter = MockAdapter()
    task = get_task("kws")

    await adapter.prepare("run-1")
    await adapter.warmup()
    results = [result async for result in adapter.measure(task, 3)]
    await adapter.teardown()

    assert [result.iter_id for result in results] == [0, 1, 2]
    assert [result.duration_us for result in results] == [1234, 1234, 1234]
    assert results[0].output["task"] == "kws"
    assert results[0].output["selected_index"] == 0


@pytest.mark.asyncio
async def test_mock_adapter_requires_prepare_before_warmup() -> None:
    adapter = MockAdapter()

    with pytest.raises(PrepareError):
        await adapter.warmup()


@pytest.mark.asyncio
async def test_mock_adapter_rejects_non_positive_iterations() -> None:
    adapter = MockAdapter()
    await adapter.prepare("run-1")
    await adapter.warmup()

    with pytest.raises(MeasureError):
        _ = [result async for result in adapter.measure(get_task("kws"), 0)]
