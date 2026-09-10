# SPDX-License-Identifier: Apache-2.0
import pytest

from signal_bench.adapters import Adapter, InferenceResult, MockAdapter
from signal_bench.tasks import get_task


def test_mock_adapter_implements_adapter_contract() -> None:
    assert isinstance(MockAdapter(), Adapter)


@pytest.mark.asyncio
async def test_mock_adapter_measure_streams_inference_results() -> None:
    adapter = MockAdapter()
    await adapter.prepare("run-1")
    await adapter.warmup()

    results = [result async for result in adapter.measure(get_task("ic"), 2)]

    assert len(results) == 2
    assert all(isinstance(result, InferenceResult) for result in results)


@pytest.mark.asyncio
async def test_mock_adapter_teardown_is_idempotent() -> None:
    adapter = MockAdapter()

    await adapter.teardown()
    await adapter.teardown()
