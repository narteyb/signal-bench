# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: N802

from __future__ import annotations

import pytest

from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError
from signal_bench.telemetry.sources.nvml import NvmlConfig, NvmlSource


class _FakeNvml:
    def __init__(self, *, count: int = 1, powers: list[int] | None = None) -> None:
        self.count = count
        self.powers = powers or [42_000]
        self.shutdown = False

    def nvmlInit(self) -> None:
        return None

    def nvmlDeviceGetCount(self) -> int:
        return self.count

    def nvmlDeviceGetHandleByIndex(self, index: int) -> str:
        return f"gpu-{index}"

    def nvmlDeviceGetPowerUsage(self, _handle: str) -> int:
        if len(self.powers) == 1:
            return self.powers[0]
        return self.powers.pop(0)

    def nvmlShutdown(self) -> None:
        self.shutdown = True


@pytest.mark.asyncio
async def test_nvml_source_yields_power_watts() -> None:
    nvml = _FakeNvml(powers=[42_500])
    source = NvmlSource(NvmlConfig(sample_rate_hz=100.0), nvml_module=nvml)

    await source.start()
    sample = await anext(source.samples())
    await source.stop()

    assert sample.source_name == "nvml"
    assert object.__getattribute__(sample, "values") == {"power": pytest.approx(42.5)}
    assert nvml.shutdown is True


@pytest.mark.asyncio
async def test_nvml_source_fails_when_no_device() -> None:
    source = NvmlSource(nvml_module=_FakeNvml(count=0))

    with pytest.raises(SourceStartError, match="found 0 CUDA devices"):
        await source.start()


@pytest.mark.asyncio
async def test_nvml_source_rejects_zero_power() -> None:
    source = NvmlSource(nvml_module=_FakeNvml(powers=[0]))
    await source.start()

    with pytest.raises(SourceDataError, match="non-positive"):
        await anext(source.samples())
