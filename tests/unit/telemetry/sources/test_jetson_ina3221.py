# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError
from signal_bench.telemetry.sources.jetson_ina3221 import (
    JetsonIna3221Config,
    JetsonIna3221Source,
)


def _write_hwmon(
    root,
    *,
    label: str = "VDD_IN",
    voltage_mv: int = 5000,
    current_ma: int = 808,
) -> None:
    hwmon = root / "hwmon1"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text("ina3221\n", encoding="utf-8")
    (hwmon / "in1_label").write_text(f"{label}\n", encoding="utf-8")
    (hwmon / "in1_input").write_text(f"{voltage_mv}\n", encoding="utf-8")
    (hwmon / "curr1_input").write_text(f"{current_ma}\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_jetson_ina3221_yields_vdd_in_power(tmp_path) -> None:
    _write_hwmon(tmp_path)
    source = JetsonIna3221Source(JetsonIna3221Config(hwmon_root=tmp_path, sample_rate_hz=100.0))

    await source.start()
    sample = await anext(source.samples())
    await source.stop()

    assert sample.source_name == "jetson_ina3221"
    assert object.__getattribute__(sample, "values") == {
        "voltage": pytest.approx(5.0),
        "current": pytest.approx(0.808),
        "power": pytest.approx(4.04),
    }


@pytest.mark.asyncio
async def test_jetson_ina3221_requires_matching_rail(tmp_path) -> None:
    _write_hwmon(tmp_path, label="VDD_SOC")
    source = JetsonIna3221Source(JetsonIna3221Config(hwmon_root=tmp_path))

    with pytest.raises(SourceStartError, match="VDD_IN"):
        await source.start()


@pytest.mark.asyncio
async def test_jetson_ina3221_rejects_zero_power(tmp_path) -> None:
    _write_hwmon(tmp_path, current_ma=0)
    source = JetsonIna3221Source(JetsonIna3221Config(hwmon_root=tmp_path))

    with pytest.raises(SourceStartError, match="non-positive"):
        await source.start()


@pytest.mark.asyncio
async def test_jetson_ina3221_rejects_zero_after_start(tmp_path) -> None:
    _write_hwmon(tmp_path)
    source = JetsonIna3221Source(JetsonIna3221Config(hwmon_root=tmp_path))
    await source.start()
    (tmp_path / "hwmon1" / "curr1_input").write_text("0\n", encoding="utf-8")

    with pytest.raises(SourceDataError, match="non-positive"):
        await anext(source.samples())
