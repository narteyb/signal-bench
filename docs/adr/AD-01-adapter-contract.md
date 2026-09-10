# AD-01: Adapter Contract

## Status

Accepted.

## Context

signal-bench needs a stable contract for target hardware adapters before concrete
MCU, local, cloud, and accelerator-specific implementations are added. The
adapter boundary must work for ESP32-S3, Nano 33 BLE Sense Rev2, NUCLEO-F401RE,
Pi 5 CPU, Jetson Orin Nano, and Modal A10G without baking target-specific
assumptions into the base layer.

Existing telemetry code uses explicit lifecycle methods and structured
dataclasses, with orchestration and database writes outside the source object.
The adapter contract follows that separation: adapters own target I/O and
measurement, while orchestrators own run rows, result persistence, telemetry
coordination, and status transitions.

## Decision

### D1: Async Contract

All adapter lifecycle methods are `async def`.

Adapter operations are I/O-bound: serial reads, subprocess calls, network calls,
flashing, or remote invocation. An async contract lets future orchestrators
interleave adapter work with telemetry and persistence without wrapping every
adapter in thread shims. Current telemetry capture is synchronous/threaded, but
the adapter boundary is the right place to establish the future coordination
model before concrete adapters exist.

### D2: Streaming Measurement Results

`measure(task, iterations)` returns an async iterator of `InferenceResult`
objects.

Each `InferenceResult` contains `iter_id`, task-specific `output`,
`duration_us`, host-side completion `timestamp`, and optional `error`. Streaming
one result at a time lets the orchestrator persist results and correlate
telemetry as each inference completes instead of waiting for a full run to
finish.

### D3: Orchestrator Owns Run Lifecycle

The orchestrator creates the `runs` row, owns the `run_id`, passes that ID to
`adapter.prepare(run_id)`, writes `results`, and marks the run completed or
failed after teardown.

Adapters do not write to `runs` or `results`. This keeps hardware concerns out
of the persistence layer and preserves the schema as the shared contract above
all adapters.

### D4: Explicit Thermal Reading Shape

`read_thermal()` returns `ThermalReading`.

`ThermalReading.available` is required. Targets without thermal sensors report
`ThermalReading(available=False)`. Targets with readable sensors set
`temperature_c`, `sensor`, and `timestamp` when available. The explicit
availability flag prevents silent `None` handling at call sites.

### D5: Explicit OS/Firmware Info Shape

`os_info()` returns `OSInfo`.

`OSInfo.target_name` and `OSInfo.firmware_version` are required. Targets that
cannot report firmware version use `"unknown"`. Optional platform-specific
fields such as CUDA, JetPack, board revision, or runtime build metadata live in
`additional`.

### D6: Shared Adapter Configuration

All adapters receive `AdapterConfig` with a required `target_id` and a nested
`TimeoutConfig`.

Default timeout values are:

- `prepare_s = 30.0`
- `warmup_s = 60.0`
- `measure_per_iteration_s = 5.0`
- `teardown_s = 15.0`

Concrete adapter families may subclass `AdapterConfig` for target-specific
settings. The base contract does not hardcode MCU-specific serial ports,
firmware paths, or board assumptions.

### D7: Typed Adapter Exceptions

Adapters raise subclasses of `AdapterError`:

- `PrepareError`
- `WarmupError`
- `MeasureError`
- `ThermalUnavailable`
- `TeardownError`
- `ConfigurationError`

The orchestrator can catch `AdapterError` for broad lifecycle recovery or
specific subclasses when policy differs. For example, `PrepareError` aborts the
run before measurement, while `ThermalUnavailable` can be logged and recorded
without necessarily failing the run.

### D8: Lifecycle Invariant

The canonical call sequence is:

```text
__init__(config) -> prepare(run_id) -> warmup() -> measure(task, iterations) -> teardown()
```

`read_thermal()` and `os_info()` are callable after `prepare()` returns
successfully. `measure()` is called exactly once per prepare/teardown cycle.
`prepare()` and `teardown()` are idempotent; `measure()` is not idempotent.

## Consequences

- Concrete adapters have a narrow, stable surface to implement.
- Orchestrators can stream results and interleave telemetry, persistence, and
  adapter progress.
- Database writes stay outside adapters, preserving the schema boundary.
- MCU-specific defaults move to `MCUAdapterBase`, not the abstract `Adapter`.
- Abstract contract files are intentionally compile-checked in T1.1; behavior
  tests land with concrete or partially concrete base implementations.

## Alternatives Considered

### Synchronous Methods

Synchronous methods would match the current telemetry collector's thread-based
implementation, but would make remote and serial adapters harder to coordinate
without wrapper threads. Async is chosen for the adapter layer before concrete
implementations lock in a less flexible pattern.

### Returning a List from `measure()`

Returning `list[InferenceResult]` is simpler for adapters, but forces the
orchestrator to wait for a full run before persisting results or aligning
telemetry. Streaming results better matches long-running targets and future
cloud adapters.

### Untyped Dictionaries

Untyped dictionaries would be flexible, but they would push contract validation
to every call site. Dataclasses keep the contract readable, typed, and stable.

### Adapter-Owned Persistence

Letting adapters write `runs` and `results` would reduce orchestrator code in
the short term, but each adapter would duplicate persistence policy and risk
schema drift. Orchestrator-owned persistence keeps adapters focused on target
hardware.
