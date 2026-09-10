# USB-Serial MCU Protocol

## Overview

This document specifies the v1 USB-serial protocol between the Python host
implementation, `MCUAdapterBase`, and MCU firmware targets. The protocol is used
inside `Adapter.measure()` to request a fixed number of task iterations and to
stream per-inference results back to the host.

Scope:

- Host to device: `RUN`
- Device to host: `RESULT`, `DONE`, `ERR`
- Transport framing, parser behavior, valid sequences, and error policy

Out of scope:

- Flashing firmware
- Task YAML loading
- Database writes
- Telemetry alignment
- Board-specific bootloaders and serial-port discovery

Status: accepted for T1.3. The host implementation is
`src/signal_bench/adapters/mcu/base.py`, and frame parsing is implemented in
`src/signal_bench/adapters/mcu/frames.py`. The tests under
`tests/adapters/mcu/` are the conformance suite for host behavior.

## Wire Format

Transport: USB-CDC serial exposed to the host through `pyserial-asyncio`.

Encoding: ASCII. Firmware must emit ASCII-safe JSON, for example by escaping
non-ASCII characters as `\uXXXX`.

Framing: newline-delimited records. Each frame is one line terminated by `LF`
(`\n`). `CRLF` is tolerated by the host parser because the parser strips line
terminators before dispatch, but firmware should emit `LF`.

Canonical separators: one space (`SP`) between fields. The host parser currently
tolerates repeated ASCII whitespace between non-JSON fields because it uses
Python `split(maxsplit=...)`; firmware should still emit the canonical form so
C++ and Python implementations stay byte-for-byte comparable.

Protocol version: v1, implicit. No version string is transmitted on the wire.
See [Versioning](#versioning) for the v2 evolution path.

## Frames

### Grammar

This EBNF describes the canonical v1 wire format. The notes after the grammar
describe host parser tolerances.

```ebnf
frame              ::= run-frame | result-frame | done-frame | err-frame

run-frame          ::= "RUN" SP task-id SP iterations LF
result-frame       ::= "RESULT" SP iter-id SP duration-us SP json-output LF
done-frame         ::= "DONE" [SP total-iterations] LF
err-frame          ::= "ERR" SP code SP message LF

task-id            ::= non-whitespace-token
iterations         ::= integer
iter-id            ::= integer
duration-us        ::= integer
total-iterations   ::= integer
code               ::= non-whitespace-token
message            ::= printable-ascii-no-LF
json-output        ::= json-text-no-LF

SP                 ::= " "
LF                 ::= "\n"
```

Parser tolerances and constraints:

- `FrameParser.parse()` strips leading and trailing whitespace before dispatch.
- Tags are case-sensitive: `RUN`, `RESULT`, `DONE`, and `ERR`.
- Unknown tags are parse errors.
- Integer fields are parsed with Python `int()`. The parser does not currently
  reject negative values, but firmware must send non-negative `iter-id` values,
  positive `iterations`, positive `duration-us`, and positive
  `total-iterations`.
- `RESULT` output is parsed with `json.loads()`. Any single-line JSON value is
  valid: object, array, string, number, boolean, or null.
- `ERR` messages may contain spaces. They may not contain a literal line feed.
- Partial byte chunks are not protocol frames. The host reads with
  `StreamReader.readline()`, so chunks are accumulated until the terminating
  line feed arrives.

### RUN

Direction: host to device.

Purpose: request execution of a task for a fixed number of measurement
iterations.

Canonical form:

```text
RUN <task_id> <iterations>
```

Example:

```text
RUN kws 5
```

`MCUAdapterBase.measure()` serializes this frame before reading device results.
The exact write is proven by
`tests/adapters/mcu/test_base_measure_happy.py`.

### RESULT

Direction: device to host.

Purpose: report one completed inference.

Canonical form:

```text
RESULT <iter_id> <duration_us> <json_output>
```

Example:

```text
RESULT 0 1200 {"iter_id":0}
```

The host converts this to `InferenceResult` with:

- `iter_id` from the frame
- `output` from parsed JSON
- `duration_us` from the frame
- `timestamp` set on the host when the frame is parsed
- `error=None`

The field order is `iter_id`, `duration_us`, `json_output`. This order is the
implemented protocol and differs from early planning notes that placed output
before duration.

### DONE

Direction: device to host.

Purpose: terminate the measurement stream.

Canonical forms:

```text
DONE
DONE <total_iterations>
```

If `total_iterations` is present, it must match the requested `RUN` iteration
count. A mismatch raises `MeasureError` on the host. If it is absent, the host
accepts the terminal frame without count validation.

### ERR

Direction: device to host.

Purpose: report one failed inference while preserving the measurement stream
where possible.

Canonical form:

```text
ERR <code> <message>
```

Example:

```text
ERR EINFER iteration 2 failed
```

The host converts each `ERR` to an `InferenceResult` with:

- an inferred `iter_id`
- `output=None`
- `duration_us=0`
- `timestamp` set on the host when the frame is parsed
- `error="<code>: <message>"`

The host does not branch by code in v1. All `ERR` frames follow the same
continuation policy described in [Error Handling](#error-handling).

## Sequence Semantics

The host owns measurement initiation. The device never starts a measurement
stream until it receives a valid `RUN` frame.

A successful run:

```text
host   -> device: RUN kws 5
device -> host  : RESULT 0 1200 {"iter_id":0}
device -> host  : RESULT 1 1201 {"iter_id":1}
device -> host  : RESULT 2 1202 {"iter_id":2}
device -> host  : RESULT 3 1203 {"iter_id":3}
device -> host  : RESULT 4 1204 {"iter_id":4}
device -> host  : DONE 5
```

Valid device frames during measurement:

- `RESULT`: yields one successful `InferenceResult`.
- `ERR`: yields one error `InferenceResult` and may continue.
- `DONE`: ends the async iterator.

Invalid device frames during measurement:

- `RUN`: unexpected device frame, host raises `MeasureError`.
- Unknown tag: parse failure, host raises `MeasureError`.
- Malformed known frame: parse failure, host raises `MeasureError`.

`measure()` must be called only after `prepare()` opens the serial link. Calling
`measure()` before prepare raises `MeasureError`.

## Error Handling

### Standard Error Codes

The v1 wire format uses symbolic string error codes. `FrameParser` accepts any
non-empty, non-whitespace code token; firmware should use this catalog:

| Code | Meaning | Typical device condition |
| --- | --- | --- |
| `EUNKNOWN` | Unknown command | Device received an unsupported frame tag |
| `EINVAL` | Invalid argument | Bad task ID, iteration count, or payload |
| `EINFER` | Inference failure | One iteration failed but firmware can continue |
| `EINTERNAL` | Internal error | Firmware crash path, out-of-memory, invariant failure |
| `ETIMEOUT` | Inference timeout | Device-side iteration timeout |
| `EHW` | Hardware fault | Sensor, peripheral, or accelerator fault |
| `ETEST` | Reserved for tests | Deterministic conformance scenarios |

`EINFER` is the code used by the T1.5 error-path tests. Numeric error codes are
not part of v1 because the shipped parser and conformance tests use symbolic
codes.

### Host Response Policy

Single `ERR`:

- Host yields one `InferenceResult` with `error` populated.
- Host keeps reading.
- Proven by `tests/adapters/mcu/test_base_measure_errors.py`.

Three consecutive `ERR` frames:

- Host yields the three error results.
- Host then raises `MeasureError`.
- Proven by `tests/adapters/mcu/test_base_measure_errors.py`.

Serial read timeout:

- Host raises `MeasureError("MCU serial read timed out")`.
- Proven by `tests/adapters/mcu/test_base_timeouts.py`.

Serial write timeout:

- Host raises `MeasureError("MCU serial write timed out")`.
- This is structural-defensive behavior in `MCUAdapterBase`; firmware cannot
  observe it directly.

Serial disconnect:

- Empty read means the USB-CDC connection dropped.
- Host raises `MeasureError("MCU serial connection dropped")`.
- Proven by `tests/adapters/mcu/test_base_measure_errors.py`.

Malformed frame:

- Decode or parse failure raises `MeasureError("MCU serial frame parse failed")`.
- Proven by `tests/adapters/mcu/test_base_measure_errors.py`.

`DONE` count mismatch:

- If the device sends `DONE <total_iterations>` and the count differs from the
  requested iterations, host raises `MeasureError`.
- Proven by `tests/adapters/mcu/test_base_measure_errors.py`.

## Lifecycle Integration

The protocol is used inside the async adapter lifecycle defined by AD-01 and
specialized for MCU targets by AD-02.

```text
orchestrator             MCUAdapterBase                  firmware
     |                         |                             |
     | prepare(run_id)         |                             |
     |------------------------>| open USB-CDC serial          |
     |                         |---------------------------->|
     | warmup()                | no generic protocol in base  |
     |------------------------>|                             |
     | measure(task, n)        |                             |
     |------------------------>| RUN <task_id> <n>            |
     |                         |---------------------------->|
     |                         | RESULT / ERR ...            |
     |                         |<----------------------------|
     | yields results          |                             |
     |<------------------------|                             |
     |                         | DONE [n]                    |
     |                         |<----------------------------|
     | teardown()              | close serial                 |
     |------------------------>|---------------------------->|
```

Lifecycle rules:

- `prepare()` opens the serial connection and stores the run ID for correlation.
- `warmup()` has no generic MCU serial protocol in v1.
- `measure()` sends exactly one `RUN` frame per prepare/teardown cycle in the
  intended v0.1 lifecycle.
- `read_thermal()` is not part of this protocol in the base implementation.
- `os_info()` is not part of this protocol in the base implementation; concrete
  adapters may query firmware version however they choose.
- `teardown()` closes the serial writer and clears host-side reader/writer
  state.

## Reference Examples

### Happy Path

Factory: `happy_path_scenario()` in `tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_measure_happy.py`.

Wire trace:

```text
host   -> device: RUN kws 5
device -> host  : RESULT 0 1200 {"iter_id":0}
device -> host  : RESULT 1 1201 {"iter_id":1}
device -> host  : RESULT 2 1202 {"iter_id":2}
device -> host  : RESULT 3 1203 {"iter_id":3}
device -> host  : RESULT 4 1204 {"iter_id":4}
device -> host  : DONE 5
```

Host behavior: yields five successful `InferenceResult` objects, then terminates
the async iterator.

### DONE Without Results

Factory: `Scenario().expect_run(...).respond_with_done(...)` in
`tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_measure_happy.py`.

Wire trace:

```text
host   -> device: RUN kws 1
device -> host  : DONE 1
```

Host behavior: yields no results and terminates normally.

### Single Mid-Stream Error

Factory: `single_error_scenario()` in `tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_measure_errors.py`.

Wire trace:

```text
host   -> device: RUN kws 4
device -> host  : RESULT 0 1200 {"iter_id":0}
device -> host  : RESULT 1 1201 {"iter_id":1}
device -> host  : ERR EINFER iteration 2 failed
device -> host  : RESULT 3 1203 {"iter_id":3}
device -> host  : DONE 4
```

Host behavior: yields successful results for iterations 0 and 1, yields an
error result for inferred iteration 2, yields a successful result for iteration
3, then terminates normally.

### Three Consecutive Errors

Factory: `consecutive_errors_scenario()` in `tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_measure_errors.py`.

Wire trace:

```text
host   -> device: RUN kws 3
device -> host  : ERR EINFER failure 0
device -> host  : ERR EINFER failure 1
device -> host  : ERR EINFER failure 2
```

Host behavior: yields three error results, then raises `MeasureError` because
the device is likely in a bad state.

### Timeout

Factory: `timeout_scenario()` in `tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_timeouts.py`.

Wire trace:

```text
host   -> device: RUN kws 1
device -> host  : <no complete frame before measure_per_iteration_s>
```

Host behavior: raises `MeasureError("MCU serial read timed out")`.

### Mid-Stream Disconnect

Factory: `disconnect_scenario()` in `tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_measure_errors.py`.

Wire trace:

```text
host   -> device: RUN kws 3
device -> host  : RESULT 0 1200 {"iter_id":0}
device -> host  : RESULT 1 1201 {"iter_id":1}
device -> host  : <EOF>
```

Host behavior: yields two successful results, then raises `MeasureError` for a
dropped serial connection.

### Malformed Frame

Factory: `malformed_frame_scenario()` in `tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_measure_errors.py`.

Wire trace:

```text
host   -> device: RUN kws 1
device -> host  : NOT_A_FRAME
```

Host behavior: raises `MeasureError("MCU serial frame parse failed")`.

### Partial Byte Chunks

Factory: raw `respond_with_raw(...)` chunks in
`tests/fixtures/mock_serial.py`.

Test coverage: `tests/adapters/mcu/test_base_measure_happy.py`.

Wire trace at byte-chunk level:

```text
device -> host: RESULT 0 1200 {"iter
device -> host: _id":0}\n
device -> host: DONE 1\n
```

Host behavior: `StreamReader.readline()` buffers until the newline and parses a
single `RESULT 0 1200 {"iter_id":0}` frame. Firmware should still write whole
newline-terminated frames when possible; the host does not require each frame to
arrive as one USB packet.

## Versioning

Current protocol: v1, implicit, no version field on the wire.

V1 is intentionally small because every deployed MCU target in v0.1 can support
the four-frame shape without negotiation.

If v2 becomes necessary, introduce a `HELLO` exchange before `RUN`:

```text
host   -> device: HELLO signal-bench-mcu 2
device -> host  : HELLO signal-bench-mcu 2
```

Backward compatibility path:

- A v2 host that receives no `HELLO` response assumes v1 if the first
  measurement can still use `RUN`.
- A v1 firmware that sees an unknown `HELLO` frame may ignore it or emit
  `ERR EUNKNOWN ...`; the v2 host must then fall back to v1 or abort before
  measuring.

No `HELLO` frame exists in v1.

## Implementation Guidance

### Host

- Use `RunFrame.serialize()` for host writes.
- Encode host frames as ASCII.
- Use `StreamReader.readline()` or equivalent line-buffering. Do not parse
  partial byte chunks as frames.
- Stamp result timestamps when `RESULT` or `ERR` is parsed on the host.
- Treat `ERR` as per-inference evidence until the consecutive-error threshold
  is reached.
- Do not reconnect automatically after disconnect. Reconnection and retry policy
  belong in orchestration.

### Firmware

- Emit canonical single-space, newline-terminated frames.
- Emit `RESULT` only after the inference has completed and duration is known.
- Serialize output as compact, one-line JSON.
- Emit `ERR` for one failed iteration when firmware can continue.
- Emit `DONE [total_iterations]` exactly once after the stream is complete.
- Prefer continuing after a single recoverable `ERR`; three consecutive `ERR`
  frames tell the host to abort.
- Flush each complete line if the serial implementation buffers writes.
- Avoid logging arbitrary text to the same serial stream during measurement.
  Unframed logs will be treated as malformed protocol frames.

## Conformance

The canonical host conformance suite is the T1.5 MCU adapter test set:

- `tests/adapters/mcu/test_base_lifecycle.py`
- `tests/adapters/mcu/test_base_measure_happy.py`
- `tests/adapters/mcu/test_base_measure_errors.py`
- `tests/adapters/mcu/test_base_timeouts.py`
- `tests/adapters/mcu/test_base_config.py`
- `tests/adapters/mcu/test_base_thermal_osinfo.py`

The scenario factories in `tests/fixtures/mock_serial.py` provide executable
wire traces for firmware authors to mirror in C++ test scaffolds.
