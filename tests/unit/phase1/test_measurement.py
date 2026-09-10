# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt

import pytest

from signal_bench.phase1.measurement import (
    compare_dual_meter,
    integrate_joules,
    power_series_by_source,
    summarize_measurement,
)
from signal_bench.phase1.runtime import GenerationResult
from signal_bench.telemetry.base import TelemetrySample


def _sample(
    source: str,
    started_at: dt.datetime,
    offset_s: float,
    power_w: float,
) -> TelemetrySample:
    return TelemetrySample(
        timestamp=started_at + dt.timedelta(seconds=offset_s),
        source_name=source,
        values={"power": power_w},
        unit_hints={"power": "W"},
    )


def _result(tokens: int) -> GenerationResult:
    now = dt.datetime.now(dt.UTC)
    return GenerationResult(
        prompt_id="p",
        started_at=now,
        finished_at=now + dt.timedelta(seconds=1),
        duration_ms=1000.0,
        first_token_ms=25.0,
        tokens_in=4,
        tokens_out=tokens,
        text="ok",
    )


def test_integrate_joules_uses_trapezoidal_rule() -> None:
    assert integrate_joules(((0.0, 1.0), (1.0, 3.0), (2.0, 3.0))) == pytest.approx(5.0)


def test_dual_meter_cross_check_accepts_close_sources() -> None:
    started_at = dt.datetime.now(dt.UTC)
    samples = (
        _sample("rail", started_at, 0.0, 9.8),
        _sample("rail", started_at, 1.0, 9.8),
        _sample("wall", started_at, 0.0, 10.0),
        _sample("wall", started_at, 1.0, 10.0),
    )

    power = power_series_by_source(samples, started_at=started_at)
    result = compare_dual_meter(power, sources=("rail", "wall"), threshold=0.10)

    assert result.compared is True
    assert result.flagged is False
    assert result.reason == "ok"
    assert result.relative_delta == pytest.approx(0.02)


def test_dual_meter_cross_check_flags_divergent_sources() -> None:
    started_at = dt.datetime.now(dt.UTC)
    samples = (
        _sample("rail", started_at, 0.0, 5.0),
        _sample("rail", started_at, 1.0, 5.0),
        _sample("wall", started_at, 0.0, 10.0),
        _sample("wall", started_at, 1.0, 10.0),
    )

    power = power_series_by_source(samples, started_at=started_at)
    result = compare_dual_meter(power, sources=("rail", "wall"), threshold=0.10)

    assert result.compared is True
    assert result.flagged is True
    assert result.reason == "divergent"
    assert result.relative_delta == pytest.approx(0.5)


def test_summarize_measurement_computes_joules_per_token_and_counts() -> None:
    started_at = dt.datetime.now(dt.UTC)
    finished_at = started_at + dt.timedelta(seconds=1)
    samples = (
        _sample("wall", started_at, 0.0, 12.0),
        _sample("wall", started_at, 1.0, 12.0),
        _sample("rail", started_at, 0.0, 11.5),
        _sample("rail", started_at, 1.0, 11.5),
    )

    summary = summarize_measurement(
        samples,
        (_result(6), _result(6)),
        started_at=started_at,
        finished_at=finished_at,
        primary_source="wall",
        cross_check_sources=("rail", "wall"),
    )

    assert summary.total_tokens_out == 12
    assert summary.energy is not None
    assert summary.energy.total_j == pytest.approx(12.0)
    assert summary.energy.joules_per_token == pytest.approx(1.0)
    assert summary.source_sample_counts == {"wall": 2, "rail": 2}
