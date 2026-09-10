# Writing an Adapter

This guide covers the target adapter contract: the code that lets
signal-bench run a benchmark on one device under test. It documents the
`Adapter` lifecycle from AD-01 and the MCU-specific base class from AD-02.
Telemetry sources are a separate contract from AD-03; this guide mentions them
only where they interact with a target run.

## What an adapter is

An adapter is the bridge between the benchmark harness and a target device. The
harness decides which task to run, how many iterations to collect, how to
persist results, and how to run telemetry beside the target. The adapter owns
the target-specific work: preparing the board, invoking inference, parsing
results, reporting target metadata, and cleaning up.

The public contract lives in `signal_bench.adapters.Adapter`. Most
microcontroller targets should start from `signal_bench.adapters.mcu.MCUAdapterBase`,
which implements the shared USB-CDC framing protocol and leaves only the
board-specific hooks to the adapter author.

## When you need to write one

Write a new target adapter when:

- Your board is not in signal-bench's supported target list.
- Your board uses a supported MCU family but needs a different flashing,
  reset, or firmware-version path.
- Your benchmark firmware uses a different invocation channel than the current
  USB-CDC protocol.
- You are benchmarking a custom board and need the run metadata to name that
  board accurately.

Do not write a target adapter to add a new power meter, temperature sensor, or
environmental probe. Those are telemetry sources, covered by AD-03 and
introduced operationally in `docs/telemetry-setup.md`.

## The contract at a glance

The generic adapter surface is six asynchronous lifecycle methods plus the
configuration object passed at construction time:

```python
@dataclass
class AdapterConfig:
    target_id: str
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)


class Adapter(ABC):
    def __init__(self, config: AdapterConfig) -> None: ...

    @abstractmethod
    async def prepare(self, run_id: str) -> None: ...

    @abstractmethod
    async def warmup(self) -> None: ...

    @abstractmethod
    async def measure(
        self,
        task: TaskSpec,
        iterations: int,
    ) -> AsyncIterator[InferenceResult]: ...

    @abstractmethod
    async def read_thermal(self) -> ThermalReading: ...

    @abstractmethod
    async def os_info(self) -> OSInfo: ...

    @abstractmethod
    async def teardown(self) -> None: ...
```

For USB-CDC microcontrollers, `MCUAdapterBase` implements those methods using
the ASCII frame protocol in `docs/usb-serial-protocol.md`. A normal MCU adapter
subclasses it and implements only:

```python
class MyBoardAdapter(MCUAdapterBase):
    async def _flash_firmware(self) -> None: ...
    async def _get_firmware_version(self) -> str: ...
```

`MCUAdapterConfig` adds `serial_port`, `baud_rate`, `flash_command`,
`firmware_path`, and `flash_before_prepare`. Invalid config fails fast with
`ConfigurationError`.

## Lifecycle: when each method is called

The harness calls the lifecycle in this order for each run:

```text
construct adapter
  -> prepare(run_id)
  -> warmup()
  -> os_info()
  -> measure(task, iterations)
       yields InferenceResult in iteration order
  -> read_thermal()
  -> teardown()
```

`teardown()` is called as best-effort cleanup after successful runs and after
most lifecycle failures. It must be idempotent. `prepare()` should also be
idempotent because a test harness may call it twice while validating recovery
behavior.

<!-- VERIFY AGAINST CONTRACT TESTS: test_prepare_idempotent and test_teardown_idempotent -->

Telemetry runs beside this lifecycle. The target adapter does not write
telemetry samples, update run rows directly, or decide whether a run is
partial. It yields inference results; the orchestrator and synthesis layers
handle persistence, telemetry coverage, and aggregation policy.

## Method-by-method

### `__init__(config)`

The constructor stores configuration and validates anything that does not
require I/O. It should not open serial ports, flash firmware, pair Bluetooth,
or reset hardware. Expensive or failure-prone work belongs in `prepare()`, so
the CLI can fail at a predictable lifecycle stage.

Raise `ConfigurationError` for invalid local configuration: missing serial
port, non-positive baud rate, impossible timeout, or incompatible option
combination. The existing `MCUAdapterBase` already validates `MCUAdapterConfig`
for blank `serial_port` and non-positive `baud_rate`.

### `prepare(run_id: str) -> None`

`prepare()` gets the run id that the harness will use for persistence and log
correlation. Open device connections here, flash firmware if configured, reset
the target, and bring the board to a known idle state. For `MCUAdapterBase`,
this opens the serial connection and, when `flash_before_prepare` is true,
calls `_flash_firmware()` before opening the port.

Return `None` on success. Raise `PrepareError` when the target cannot be made
ready: serial open failure, flash failure, reset failure, timeout, or a missing
firmware artifact that was only discoverable at prepare time.

Common pitfall: doing half of the setup in `__init__` and half in `prepare()`.
Keep hardware-side state changes in `prepare()` so tests can construct the
adapter without touching hardware.

### `warmup() -> None`

`warmup()` lets the target settle before measurement. Many MCU targets need no
warmup; `MCUAdapterBase` implements a no-op default with timeout enforcement.
Override it only when the firmware or board needs pre-measurement commands,
cache priming, or thermal stabilization.

Raise `WarmupError` if warmup cannot complete. Do not yield measurements from
warmup and do not persist anything here; warmup is outside the measured
iteration stream.

### `measure(task: TaskSpec, iterations: int) -> AsyncIterator[InferenceResult]`

`measure()` is the only streaming method. The harness passes the task metadata
and the number of iterations to collect. The adapter yields one
`InferenceResult` per completed inference, ordered by `iter_id`.

`TaskSpec` contains `task_id`, `model_path`, `input_data_path`,
`expected_output_shape`, and free-form `metadata`. The adapter may use those
paths to choose firmware-side assets or host-side input payloads. It should not
mutate the task object.

Each `InferenceResult` includes:

- `iter_id`: the zero-based iteration number.
- `output`: the parsed target output.
- `duration_us`: target-reported or host-measured inference duration in
  microseconds.
- `timestamp`: when the result was observed by the adapter.
- `error`: optional per-iteration error string.

For `MCUAdapterBase`, `measure()` writes a `RUN` frame, parses `RESULT`, `ERR`,
and `DONE` frames, yields individual `ERR` frames as error results, and raises
`MeasureError` after three consecutive target errors. Results yielded before a
later `MeasureError` remain valid and can be persisted by the harness.

<!-- VERIFY AGAINST CONTRACT TESTS: test_single_error_yields_error_result_continues and test_three_consecutive_errors_raise_measure_error -->

Raise `MeasureError` for invalid iteration counts, measurement before prepare,
serial disconnect, parse failure, timeout, unexpected frame, or a final count
mismatch. Do not convert infrastructure failures into successful results with
`error` strings; reserve result-level `error` for target-reported inference
errors that still preserve the stream.

Common pitfall: buffering all results and returning a list. The contract is an
async iterator so long runs can stream results while telemetry continues.

### `read_thermal() -> ThermalReading`

`read_thermal()` returns the target-side thermal state if the target can expose
it. If no target thermal sensor exists, return `ThermalReading(available=False)`
rather than inventing a value. `MCUAdapterBase` already uses this unavailable
default.

Raise `ThermalUnavailable` only when the target is expected to provide a
reading but cannot do so. That distinction lets the harness separate "this
target has no sensor" from "this target's sensor failed."

### `os_info() -> OSInfo`

`os_info()` returns stable target metadata for the run: `target_name`,
`firmware_version`, and optional string key/value pairs in `additional`.
`MCUAdapterBase` fills `target_name` from `config.target_id` and calls
`_get_firmware_version()` for the version string.

Raise `PrepareError` if metadata cannot be read because the target is not ready
or the firmware query times out. The metadata is part of run provenance; do not
silently return placeholder versions unless the placeholder is the adapter's
explicit documented behavior for a mock target.

### `teardown() -> None`

`teardown()` closes device resources and leaves the target in a safe state. It
must be safe to call after a partial setup failure and safe to call more than
once. `MCUAdapterBase` closes its serial writer if one exists and clears its
reader/writer references.

Raise `TeardownError` for cleanup failures that the harness should record.
Teardown errors should not mask the original lifecycle error; the harness owns
that policy, but adapter authors should make teardown narrow and predictable.

<!-- VERIFY AGAINST CONTRACT TESTS: test_teardown_timeout_raises_teardown_error -->

### `_flash_firmware() -> None` for `MCUAdapterBase`

Implement this hook when your MCU adapter uses `MCUAdapterBase`. It is called
from `prepare()` only when `flash_before_prepare` is true. Use it to run the
board-specific flash command, copy firmware to a mass-storage bootloader, or
invoke a vendor tool.

Raise `PrepareError` for flash failures. Keep command construction explicit and
avoid reading environment variables inside this method unless they are part of
the adapter's documented config.

### `_get_firmware_version() -> str` for `MCUAdapterBase`

Implement this hook to query the benchmark firmware version. The base class
wraps it in the prepare timeout budget when `os_info()` runs.

Return a short stable string, such as a firmware semantic version or git SHA.
Raise `PrepareError` if the adapter cannot query a version from a target that
should provide one.

## Example skeleton

The standalone version of this example lives at
`docs/writing-an-adapter/skeleton.py`. It is a no-hardware mock target: useful
for copying the lifecycle shape before replacing the simulated command path
with real UART, BLE, GPIO, or flashing code.

```python
from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator
from dataclasses import dataclass

from signal_bench.adapters import (
    Adapter,
    AdapterConfig,
    ConfigurationError,
    InferenceResult,
    MeasureError,
    OSInfo,
    PrepareError,
    TaskSpec,
    ThermalReading,
    WarmupError,
)


@dataclass(frozen=True, kw_only=True)
class MockSerialAdapterConfig(AdapterConfig):
    firmware_version: str = "mock-firmware-0"
    duration_us_base: int = 1_000


class MockSerialAdapter(Adapter):
    def __init__(self, config: MockSerialAdapterConfig) -> None:
        super().__init__(config)
        if config.duration_us_base <= 0:
            msg = "duration_us_base must be positive"
            raise ConfigurationError(msg)
        self._mock_config = config
        self._prepared = False
        self._run_id: str | None = None

    async def prepare(self, run_id: str) -> None:
        if self._prepared:
            return
        if not run_id:
            raise PrepareError("run_id is required")
        await asyncio.sleep(0)
        self._run_id = run_id
        self._prepared = True

    async def warmup(self) -> None:
        if not self._prepared:
            raise WarmupError("prepare() must complete before warmup()")
        await asyncio.sleep(0)

    async def measure(
        self,
        task: TaskSpec,
        iterations: int,
    ) -> AsyncIterator[InferenceResult]:
        if not self._prepared:
            raise MeasureError("prepare() must complete before measure()")
        if iterations <= 0:
            raise MeasureError("iterations must be positive")

        for iter_id in range(iterations):
            await asyncio.sleep(0)
            yield InferenceResult(
                iter_id=iter_id,
                output={"task_id": task.task_id, "label": "mock", "score": 1.0},
                duration_us=self._mock_config.duration_us_base + iter_id,
                timestamp=dt.datetime.now(dt.UTC),
            )

    async def read_thermal(self) -> ThermalReading:
        return ThermalReading(available=False)

    async def os_info(self) -> OSInfo:
        if not self._prepared:
            raise PrepareError("prepare() must complete before os_info()")
        return OSInfo(
            target_name=self.config.target_id,
            firmware_version=self._mock_config.firmware_version,
            additional={"example": "no-hardware"},
        )

    async def teardown(self) -> None:
        await asyncio.sleep(0)
        self._prepared = False
        self._run_id = None
```

For a production USB-CDC MCU adapter, keep the lifecycle behavior above but
subclass `MCUAdapterBase` instead of `Adapter`. Then move serial framing back
to the base class and implement `_flash_firmware()` plus
`_get_firmware_version()`.

## Testing your adapter

Start with the adapter tests under `tests/adapters/mcu/`. They cover
configuration validation, prepare/teardown idempotence, timeout translation,
measurement stream behavior, target error frames, malformed frames, serial
drops, thermal defaults, and firmware-version metadata.

If you subclass `MCUAdapterBase`, use the existing fixtures in
`tests/fixtures/mock_serial.py` and `tests/fixtures/test_helpers.py` as the
pattern for injecting fake serial input. The tests should prove three things
before you touch hardware: invalid config fails early, lifecycle methods raise
the right adapter exception, and `measure()` yields ordered results while
preserving already-yielded results after later failures.

<!-- VERIFY AGAINST CONTRACT TESTS: test_serial_drop_mid_stream_raises_measure_error and test_done_total_mismatch_raises_measure_error -->

After contract tests pass, verify the hardware path with your actual board:
flash command, reset timing, serial port discovery, firmware-version query, and
one short benchmark run. Keep hardware-only facts out of the adapter contract
itself; put them in the adapter's README or target notes.

## Cross-references

- AD-01: Adapter Contract. The source of the six-method async lifecycle and
  exception hierarchy.
- AD-02: MCU Adapter Base. The source of the USB-CDC base class, ASCII frame
  handling, flash hook, firmware-version hook, and timeout policy.
- AD-03: Telemetry Orchestrator. Explains how target measurement runs alongside
  telemetry sources without making the adapter responsible for telemetry.
- `docs/usb-serial-protocol.md`: frame format used by `MCUAdapterBase`.
- `docs/telemetry-setup.md`: hardware setup for telemetry sources that run
  beside, not inside, the target adapter.
- `README.md`: public quickstart, schema overview, and reproducibility posture.
