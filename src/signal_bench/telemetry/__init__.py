# SPDX-License-Identifier: Apache-2.0
"""Telemetry capture abstractions."""

from signal_bench.telemetry.base import (
    OrchestratorConfig,
    TelemetrySample,
    TelemetrySource,
)
from signal_bench.telemetry.collector import CollectorResult, TelemetryCollector
from signal_bench.telemetry.exceptions import (
    ConfigurationError,
    OrchestratorError,
    SourceDataError,
    SourceDisconnectError,
    SourceStartError,
    TelemetryError,
    TelemetryUnavailableError,
)
from signal_bench.telemetry.mock import MockTelemetrySource
from signal_bench.telemetry.orchestrator import OrchestratorState, TelemetryOrchestrator
from signal_bench.telemetry.sources import (
    Bme280Config,
    Bme280Source,
    FnirsiHidSource,
    FnirsiHidSourceConfig,
    FnirsiSource,
    FnirsiSourceConfig,
    Ina219Config,
    Ina219Source,
    MockBME280Config,
    MockBME280Source,
    MockINA219Config,
    MockINA219Source,
)

__all__ = [
    "Bme280Config",
    "Bme280Source",
    "CollectorResult",
    "ConfigurationError",
    "FnirsiHidSource",
    "FnirsiHidSourceConfig",
    "FnirsiSource",
    "FnirsiSourceConfig",
    "Ina219Config",
    "Ina219Source",
    "MockBME280Config",
    "MockBME280Source",
    "MockINA219Config",
    "MockINA219Source",
    "MockTelemetrySource",
    "OrchestratorConfig",
    "OrchestratorError",
    "OrchestratorState",
    "SourceDataError",
    "SourceDisconnectError",
    "SourceStartError",
    "TelemetryCollector",
    "TelemetryError",
    "TelemetryOrchestrator",
    "TelemetrySample",
    "TelemetrySource",
    "TelemetryUnavailableError",
]
