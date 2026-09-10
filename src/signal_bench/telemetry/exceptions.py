# SPDX-License-Identifier: Apache-2.0
"""Telemetry exception hierarchy."""


class TelemetryError(RuntimeError):
    """Base class for telemetry failures handled by the orchestrator."""


class SourceStartError(TelemetryError):
    """Raised when a telemetry source cannot start.

    Expected orchestrator response: abort the run before measurement begins.
    Starting a run with known-missing telemetry would create misleading data.
    """


class SourceDisconnectError(TelemetryError):
    """Raised when a source disconnects after a run has started.

    Expected orchestrator response: mark the run telemetry as partial, record
    the source name, and continue collecting from remaining sources.
    """


class SourceDataError(TelemetryError):
    """Raised when a source emits malformed or physically implausible data.

    Expected orchestrator response: mark the run telemetry as partial for that
    source and continue unless all sources have failed.
    """


class OrchestratorError(TelemetryError):
    """Raised when the telemetry orchestrator itself fails.

    Expected caller response: fail or abort the benchmark run because telemetry
    coordination can no longer be trusted.
    """


class ConfigurationError(TelemetryError):
    """Raised when telemetry configuration is invalid before a run starts."""


class TelemetryUnavailableError(TelemetryError):
    """Raised when a source's optional library or hardware is unavailable.

    Kept for M2a compatibility. Error messages should include actionable
    installation guidance, such as ``Install with: uv sync --extra telemetry``.
    """
