# SPDX-License-Identifier: Apache-2.0
import datetime as dt
from dataclasses import FrozenInstanceError

import pytest

from signal_bench.telemetry import TelemetrySample, TelemetrySource, TelemetryUnavailableError


def test_telemetry_sample_is_frozen_hashable_and_slotted() -> None:
    sample = TelemetrySample(
        timestamp=dt.datetime.now(dt.UTC),
        source="mock",
        metric="voltage_v",
        value=5.0,
    )

    assert hash(sample)
    assert not hasattr(sample, "__dict__")
    with pytest.raises(FrozenInstanceError):
        sample.value = 4.9  # type: ignore[misc]


def test_telemetry_source_is_abstract() -> None:
    with pytest.raises(TypeError):
        TelemetrySource()  # type: ignore[abstract]


def test_telemetry_unavailable_error_inherits_runtime_error() -> None:
    assert issubclass(TelemetryUnavailableError, RuntimeError)
