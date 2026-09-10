# SPDX-License-Identifier: Apache-2.0
"""Exception hierarchy for signal-bench hardware adapters."""


class AdapterError(RuntimeError):
    """Base class for adapter failures.

    Orchestrators should catch this type when they need broad recovery around
    adapter lifecycle operations. More specific subclasses communicate which
    lifecycle stage failed and how the run should be handled.
    """


class PrepareError(AdapterError):
    """Raised when an adapter cannot prepare a target for a run.

    Expected orchestrator response: abort the run before warmup or measurement,
    mark the run failed, and call teardown as a best-effort cleanup.
    """


class WarmupError(AdapterError):
    """Raised when warmup cannot complete successfully.

    Expected orchestrator response: mark the run failed because the target never
    reached a valid measurement state, then call teardown.
    """


class MeasureError(AdapterError):
    """Raised when measurement fails after warmup.

    Expected orchestrator response: persist any results already yielded, mark
    the run failed or partial according to policy, and call teardown.
    """


class ThermalUnavailable(AdapterError):
    """Raised when a thermal reading is requested but cannot be provided.

    Expected orchestrator response: log a warning, record explicit thermal
    unavailability, and continue unless the current task requires thermal data.
    """


class TeardownError(AdapterError):
    """Raised when target cleanup fails.

    Expected orchestrator response: mark cleanup failure in run metadata and
    avoid masking an earlier lifecycle error.
    """


class ConfigurationError(AdapterError):
    """Raised when adapter configuration is invalid.

    Expected orchestrator response: fail fast before creating hardware-side
    state or beginning the run lifecycle.
    """
