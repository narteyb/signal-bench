# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from signal_bench.telemetry.exceptions import SourceStartError
from signal_bench.telemetry.sources.jetson_thermal import JetsonThermalConfig, JetsonThermalSource


def _write_zone(root, index: int, zone_type: str, temp_mc: int) -> None:
    zone = root / f"thermal_zone{index}"
    zone.mkdir(parents=True)
    (zone / "type").write_text(f"{zone_type}\n", encoding="utf-8")
    (zone / "temp").write_text(f"{temp_mc}\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_jetson_thermal_yields_grouped_temperatures(tmp_path) -> None:
    _write_zone(tmp_path, 0, "cpu-thermal", 40718)
    _write_zone(tmp_path, 1, "gpu-thermal", 40843)
    source = JetsonThermalSource(JetsonThermalConfig(thermal_root=tmp_path, sample_rate_hz=100.0))

    await source.start()
    sample = await anext(source.samples())
    await source.stop()

    assert sample.source_name == "jetson_thermal"
    assert object.__getattribute__(sample, "values") == {
        "cpu_thermal_c": pytest.approx(40.718),
        "gpu_thermal_c": pytest.approx(40.843),
    }


@pytest.mark.asyncio
async def test_jetson_thermal_requires_readable_zone(tmp_path) -> None:
    source = JetsonThermalSource(JetsonThermalConfig(thermal_root=tmp_path))

    with pytest.raises(SourceStartError, match="no readable"):
        await source.start()
