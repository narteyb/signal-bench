# SPDX-License-Identifier: Apache-2.0
"""Public adapter contract API."""

from signal_bench.adapters.base import (
    Adapter,
    AdapterConfig,
    InferenceResult,
    OSInfo,
    ThermalReading,
    TimeoutConfig,
)
from signal_bench.adapters.exceptions import (
    AdapterError,
    ConfigurationError,
    MeasureError,
    PrepareError,
    TeardownError,
    ThermalUnavailable,
    WarmupError,
)
from signal_bench.adapters.hailo import (
    HailoAdapter,
    HailoAdapterConfig,
    HailoPreflightInfo,
    preflight_hailo10h,
)
from signal_bench.adapters.mcu.task import TaskSpec
from signal_bench.adapters.mock import MockAdapter, MockAdapterConfig

__all__ = [
    "Adapter",
    "AdapterConfig",
    "AdapterError",
    "ConfigurationError",
    "HailoAdapter",
    "HailoAdapterConfig",
    "HailoPreflightInfo",
    "InferenceResult",
    "MeasureError",
    "MockAdapter",
    "MockAdapterConfig",
    "OSInfo",
    "PrepareError",
    "TaskSpec",
    "TeardownError",
    "ThermalReading",
    "ThermalUnavailable",
    "TimeoutConfig",
    "WarmupError",
    "preflight_hailo10h",
]
