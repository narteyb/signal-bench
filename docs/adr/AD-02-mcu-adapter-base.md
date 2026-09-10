# AD-02: MCU Adapter Base

## Status

Accepted.

## Context

AD-01 defines the six-method async adapter contract shared by all targets. MCU
targets need a concrete shared layer for USB-CDC serial lifecycle management and
host-side measurement protocol handling before board-specific ESP32-S3, Nano 33
BLE Sense Rev2, and NUCLEO-F401RE adapters are added.

The shared MCU layer must stay below orchestration and persistence. It opens and
closes the serial link, sends measurement commands, parses device frames, and
yields `InferenceResult` objects. It does not create runs, write results, own
database state, or hide hardware failures behind automatic reconnection.

## Decision

### D2-A: Serial Library

Use `pyserial-asyncio` for USB-CDC serial I/O.

It wraps pyserial with asyncio stream primitives, matches the async contract from
AD-01, and avoids a custom Protocol implementation. No existing serial code was
present in `src/signal_bench`, so there was no local convention to preserve.

### D2-B: MCU Adapter Configuration

Define `MCUAdapterConfig(AdapterConfig)` with:

- `serial_port`
- `baud_rate`
- `flash_command`
- `firmware_path`
- `flash_before_prepare`

`serial_port` and `baud_rate` are validated by `MCUAdapterBase`. Flash settings
are stored for board-specific subclasses and future firmware tooling, but the
shared base does not interpret concrete toolchain commands.

### D2-C: ASCII Frame Parser

Define newline-delimited ASCII frames parsed by `FrameParser`:

- `RUN <task_id> <iterations>`
- `RESULT <iter_id> <duration_us> <json_output>`
- `DONE [total_iterations]`
- `ERR <code> <message>`

Each frame has a dataclass representation. Dispatch is keyed by the first token
and delegated to the frame class, keeping parsing extensible for the formal
T1.3 protocol specification and later protocol revisions. The protocol is
specified in [USB-Serial MCU Protocol](../usb-serial-protocol.md).

### D2-D: MCU Base Hooks

`MCUAdapterBase` implements the AD-01 lifecycle methods and leaves two abstract
hooks for concrete board adapters:

- `_flash_firmware()`
- `_get_firmware_version()`

`read_thermal()` returns `ThermalReading(available=False)` by default. Boards
with readable thermal sensors override it; sensorless boards inherit the default.

### D2-E: Timeout Enforcement

Lifecycle I/O is wrapped with `asyncio.wait_for` using `config.timeouts`.

Timeouts raise lifecycle-specific adapter exceptions. Prepare, firmware version
reads, warmup, and teardown raise `PrepareError`, `WarmupError`, or
`TeardownError` as appropriate. Measurement serial reads and writes raise
`MeasureError`.

### D2-F: Measurement Error Handling

`ERR` frames are treated as per-inference failures first.

The adapter yields an `InferenceResult` with `error` populated for each `ERR`
frame so the orchestrator can persist partial evidence. If three consecutive
`ERR` frames arrive, `measure()` raises `MeasureError` because the device is
likely in a bad state. If the serial connection drops, `measure()` raises
`MeasureError` immediately. The adapter does not transparently reconnect.

`InferenceResult.timestamp` is host-side for T1.2. The timestamp is set when the
host parses the `RESULT` or `ERR` frame. Device-side timestamps are deferred to
T5.3 if telemetry alignment requires them.

### D2-G: Flash Behavior

`prepare()` calls `_flash_firmware()` only when
`config.flash_before_prepare=True`.

Defaulting to no flash supports benchmark matrix runs where firmware is flashed
once and reused for many measurements. Concrete board adapters may choose
different defaults in their own config factories or orchestration presets.

## Consequences

- Board-specific MCU adapters can share serial lifecycle and frame handling.
- The shared base remains abstract and hardware-agnostic.
- The orchestrator remains responsible for run lifecycle, persistence, retries,
  and recovery policy.
- `TaskSpec` becomes the concrete task payload for `Adapter.measure()` before
  any callers depend on the previous `object` placeholder.
- T1.3 can formalize the implemented protocol without needing to invent a
  second host-side shape.

## Alternatives Considered

### Custom Async Serial Protocol

A custom asyncio Protocol around pyserial would offer more control but add
complexity before the firmware protocol is stable. `pyserial-asyncio` is mature
enough for this layer and keeps the implementation small.

### Unconditional Flash in `prepare()`

Flashing on every prepare would simplify state assumptions but wastes seconds on
each matrix run and adds avoidable wear and setup latency. A config flag gives
the orchestrator explicit control.

### Raising on Every `ERR` Frame

Failing the run on the first device `ERR` would discard useful partial
measurement evidence. Yielding error results preserves per-inference failures
while still escalating repeated errors.

### Transparent Serial Reconnect

Automatic reconnect would hide hardware instability and contaminate timing
measurements. Reconnection and retry policy belong in orchestration, not in the
adapter.
