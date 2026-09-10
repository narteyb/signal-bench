# AD-03: Telemetry Orchestrator

## Status

Accepted.

## Context

M2a introduced a synchronous, thread-based `TelemetryCollector` with a polling
`TelemetrySource` interface. That collector is useful for mock-driven smoke
tests, but it does not match the async adapter contract from AD-01 or the
async USB-serial implementation in AD-02. Benchmark orchestration needs adapter
measurement, telemetry capture, and persistence to run in one async coordination
model.

T7 defines the async telemetry path that later tasks implement. T7.1 establishes
the source contract, sample shape, exception hierarchy, dependency choice, and
lifecycle invariants. The existing synchronous collector remains in place for
current CLI and test coverage until T7.2 intentionally introduces the async
orchestrator implementation.

The database schema already contains `telemetry_samples` and the M2a
`runs.telemetry_partial` / `runs.telemetry_partial_sources` columns, so no
schema migration is required for this contract.

## Decision

### D9-A: New Async Orchestrator Beside Existing Collector

Add a new async `TelemetryOrchestrator` path instead of retrofitting the
existing synchronous `TelemetryCollector`.

`MCUAdapterBase` is async by AD-01 and AD-02. The orchestrator must run telemetry
capture concurrently with adapter `measure()` calls without thread bridges. A
hybrid sync/async collector would add shutdown, exception, and database-session
complexity. The synchronous collector remains available until the async path is
implemented and callers are migrated deliberately.

### D9-B: Async Source Lifecycle

`TelemetrySource` has an async lifecycle:

- `name`
- `start()`
- `samples()`
- `stop()`

`samples()` is an async iterator of `TelemetrySample` objects. This mirrors
`Adapter.measure()` streaming results from AD-01: the orchestrator can consume
telemetry incrementally while the benchmark is running. `start()` and `stop()`
are explicit so hardware setup and cleanup are not hidden inside iteration.

The M2a sync hooks (`is_available()`, `open()`, `sample()`, `close()`) remain as
compatibility methods while the existing collector still exists. They are not
the T7 contract.

### D9-C: Grouped Telemetry Sample Shape

`TelemetrySample` stores:

- `timestamp`
- `source_name`
- `values: dict[str, float]`
- `unit_hints: dict[str, str]`

Grouped `values` let one source emit related measurements together, for example
FNB58 voltage/current/power or BME280 temperature/humidity/pressure. The source
timestamp is authoritative; the orchestrator does not overwrite it. `unit_hints`
remain optional metadata for displays and exports.

The class accepts the previous scalar `source` / `metric` / `value` shape for
M2a compatibility. The async writer in T7.2 will fan grouped values out to the
existing `telemetry_samples` table's `source`, `metric`, and `value` columns.

### D9-D: Source Tasks and Single Database Writer

The async orchestrator runs one `asyncio.Task` per source and one database writer
task connected by an `asyncio.Queue`.

Source tasks consume `source.samples()` and enqueue samples. The writer task
batch-inserts samples and is the only task that owns database writes. This avoids
SQLAlchemy session contention and gives the queue a natural back-pressure point
if a source produces faster than the database can persist.

### D9-E: Typed Telemetry Exceptions and Partial Policy

Telemetry failures use subclasses of `TelemetryError`:

- `SourceStartError`
- `SourceDisconnectError`
- `SourceDataError`
- `OrchestratorError`
- `ConfigurationError`

If a source fails to start, the run aborts before measurement begins. If a source
disconnects or emits malformed data after the run starts, the orchestrator marks
`runs.telemetry_partial = TRUE`, records the source in
`telemetry_partial_sources`, and continues collecting from remaining sources. If
all sources fail or the orchestrator itself fails, the run cannot be trusted and
the orchestrator raises `OrchestratorError`.

This follows the AD-02 pattern: preserve partial evidence where meaningful, but
escalate repeated or system-level failure.

### D9-F: BLE Library

Use `bleak` for FNB58 BLE work.

`bleak` is the mature cross-platform async BLE library and supports macOS, which
matters for the M1 Max development host. `aioble` does not satisfy the macOS
requirement. The abstract contract does not import `bleak`; only the concrete
FNB58 source in T7.3 will.

### D9-G: Source Organization

Telemetry source implementations live under:

```text
src/signal_bench/telemetry/
  base.py
  exceptions.py
  orchestrator.py
  sources/
    __init__.py
    fnirsi.py
    ina219_mock.py
    bme280_mock.py
```

T7.1 creates the contract, exceptions, and source package marker. T7.2 creates
the orchestrator. T7.3 and T7.4 add concrete sources.

### D9-H: Lifecycle Invariants

`start()` and `stop()` are idempotent. `samples()` yields until `stop()` is
called or an unrecoverable source error occurs, and is not re-entered after
shutdown.

The orchestrator starts sources concurrently, stops them concurrently, drains
the queue before final shutdown, and updates the run's telemetry partial fields
after all source tasks have settled. Sample timestamps come from sources so
future hardware-side timestamps can be preserved.

## Consequences

- T7 source implementations share the same async dialect as adapters.
- The existing synchronous collector remains stable while T7 is built.
- T7.2 can implement persistence without changing the database schema.
- FNB58 BLE can use `bleak` without making the abstract contract BLE-specific.
- Mocked I2C sources can use the same async source contract as the real BLE
  source.

## Alternatives Considered

### Retrofitting the Synchronous Collector

Converting the existing threaded collector in place would risk breaking the M2a
CLI and test path before the async replacement exists. Keeping the old collector
and adding the async orchestrator beside it makes the migration explicit.

### Direct Database Writes From Sources

Letting each source write its own samples would make source implementations
stateful and persistence-aware. It would also require one session per source or
shared-session coordination. A single writer task keeps source code focused on
hardware and avoids session contention.

### One Scalar Value Per Sample

The existing `telemetry_samples` table stores scalar rows, but source hardware
often captures related values at one timestamp. Grouped `TelemetrySample.values`
preserves that relationship in memory; the writer can fan out rows for the
current schema.

### BLE-Specific Base Types

FNB58 is the first real T7 source, but the contract must also work for mocked
I2C sources and future USB/network telemetry. Keeping `bleak` out of the base
contract prevents BLE concerns from leaking into unrelated sources.

## T7.2 Implementation Notes

### Grouped Sample Fanout

`TelemetryOrchestrator` persists one scalar row per metric in the existing
`telemetry_samples` table. A source sample such as:

```python
TelemetrySample(
    timestamp=ts,
    source_name="fnb58",
    values={"voltage": 5.02, "current": 0.123, "power": 0.617},
)
```

is written as three rows with the same `run_id`, timestamp, and source, and
metric/value pairs of `voltage`, `current`, and `power`. The current
schema has no unit column, so `unit_hints` remain in-memory metadata until a
future export or schema revision needs them.

### Queue Back-Pressure

The orchestrator uses a bounded `asyncio.Queue` with the
`OrchestratorConfig.queue_maxsize` default of 1024 grouped samples. Source pumps
use `await queue.put(sample)`, so a stalled writer naturally slows sources
instead of allowing unbounded memory growth. This is acceptable for the expected
10-100 Hz telemetry rates.

### Sync Collector Coexistence

The M2a synchronous `TelemetryCollector` remains unchanged and is not
deprecated by T7.2. Existing CLI and smoke paths can keep using it. New async
benchmark orchestration uses `TelemetryOrchestrator`; any collector deprecation
is a separate cleanup decision after T7 lands.

## T7.3 Implementation Notes

### FNB58 Protocol Reference

FNIRSI does not publish an FNB58 BLE protocol. T7.3 uses community-reported BLE
facts from Parker Reed's `fnirsi-fnb58.py` gist:

<https://gist.github.com/parkerlreed/0ce45e907ce536a0541afb90b5b49350>

The implementation uses `bleak`, writes `aa8100f4` and `aa8200a7` to
characteristic `0000ffe9-0000-1000-8000-00805f9b34fb`, subscribes to
notifications from `0000ffe4-0000-1000-8000-00805f9b34fb`, and decodes
voltage/current/power from three little-endian signed 32-bit values at byte
offset 21 scaled by 10000. A Boondock Battery Life writeup independently
documents the same FNB58 BLE exploration path and points to the mature
`baryluk/fnirsi-usb-power-data-logger` USB implementation as the fallback
reference if BLE proves unstable.

### Canonical FNB58 Metric Names

FNB58 samples use:

- `voltage` in volts
- `current` in amps
- `power` in watts

These names intentionally avoid device-specific prefixes. If later sources need
rail-specific precision, they can add source-specific metadata or distinct
source names while keeping the common metric names for comparable power traces.

### BLE Disconnect Mapping

| BLE condition | Telemetry exception |
|---|---|
| `BleakError` during connect or notification setup | `SourceStartError` |
| mid-run disconnect callback | `SourceDisconnectError` via timeout check |
| timeout while disconnected | `SourceDisconnectError` |
| timeout while still connected | no exception; continue waiting |
| malformed packet | warn and skip |
| three consecutive malformed packets | `SourceDataError` |

T7.3 does not implement auto-reconnect. Disconnects are treated as partial
telemetry events and are handled by `TelemetryOrchestrator`.

## T7.4 Implementation Notes

### Canonical Metric Names

Telemetry sources use shared metric names and carry device identity in
`source_name`.

| Source | Metrics | Units |
|---|---|---|
| `fnb58` | `voltage`, `current`, `power` | V, A, W |
| `ina219_*` | `voltage`, `current`, `power` | V, A, W |
| `bme280_*` | `temperature`, `humidity`, `pressure` | degC, %, hPa |

Multiple INA219 rails are disambiguated by source name, for example
`ina219_main` or `ina219_aux`, rather than by inventing rail-specific metric
names. This keeps downstream queries such as "all voltage measurements" simple
while still allowing callers to filter by source.

### Mock Source Identity

T7.4 mock I2C placeholders use a `mock_` source-name prefix:

- `mock_ina219_main`
- `mock_bme280_lab`

When real MCP2221A-backed drivers replace them in M2 Stage 2, source names drop
the prefix, for example `ina219_main`. This makes real-vs-synthetic telemetry
easy to filter in database queries and post-run analysis.

### Placeholder Scope

The mock INA219 and BME280 sources emit `TelemetrySample` objects directly and
do not simulate I2C registers, addresses, bus failures, or MCP2221A behavior.
They are happy-path software sources for exercising the orchestrator and CLI
before hardware arrives. Real I2C drivers replace them rather than extending
them.

## T7.5 Implementation Notes

### CLI Argument Shape

`signal-bench telemetry test` runs the M2 Stage 1 roster for a requested
duration:

```text
signal-bench telemetry test --duration SECONDS [--fnb58-address ADDRESS] [--no-fnb58]
                            [--output table|json|csv] [--quiet]
```

The command accepts `--db` using the existing CLI database-path convention.
`--duration` is validated by the command so configuration errors use the
documented telemetry-test exit code.

### FNB58 Resolution Policy

The source roster always includes `mock_ina219_main` and `mock_bme280_lab`.
FNB58 is included only when `--fnb58-address` is provided or `FNB58_ADDRESS` is
set. The flag wins over the environment variable. `--no-fnb58` skips FNB58 even
when an address is present, which keeps CI and pre-hardware smoke runs
deterministic.

If no FNB58 address is configured, the command warns in table mode and proceeds
with mocks only. This is not a partial telemetry run because the source was
never part of the requested roster.

### Exit Codes

| Code | Meaning |
|---|---|
| 0 | clean run, all requested sources OK |
| 1 | clean run but telemetry was partial due to a requested source failure |
| 2 | orchestrator or source startup failure |
| 3 | CLI configuration error |
| 4 | database open, migration, or run-row creation error |

The `runs` schema has no `kind` column. T7.5 records the telemetry-test kind in
`runs.extra["kind"]` and uses sentinel `targets` / `tasks` rows for the
non-null foreign-key requirements.

## T7.6 Implementation Notes

### Failure-Mode Coverage Matrix

T7.6 adds a dedicated `ProgrammableMockSource` test helper and covers the
orchestrator failure modes from AD-03 and the T7 implementation notes:

| Scenario | Expected behavior |
|---|---|
| one source disconnects mid-run | run continues; `telemetry_partial=true`; failed source listed |
| all sources disconnect | `OrchestratorError`; partial sources recorded |
| source fails to start | `SourceStartError`; no telemetry rows written |
| one of several sources fails to start | already-started sources are stopped |
| source raises `SourceDataError` | source marked partial; remaining sources continue |
| source raises another `TelemetryError` | source marked partial; remaining sources continue |
| source raises unexpected exception | source marked partial; remaining sources continue |
| source iterator ends unexpectedly | source marked partial |
| stop before start / stop twice | idempotent |
| queue fills under slow DB writer | source pump back-pressure bounds sample throughput |

### Rate Tolerance

T7.6 keeps rate assertions tolerant of asyncio scheduler jitter. Tests assert
within broad tolerance bands rather than exact sample counts; the observed
mock INA219 rate can be roughly 10% below nominal on local runs due to
`asyncio.sleep()` scheduling and DB writer overhead.

### CLI Regression Coverage

CLI coverage now includes table, JSON, and CSV output; quiet mode; FNB58 address
resolution with flag-over-environment precedence; mocks-only runs; and a
subprocess SIGINT test. The SIGINT test sends Ctrl-C to a running telemetry
test and verifies the command prints a summary and marks the run `interrupted`.

### Coverage Result

After T7.6, `signal_bench.telemetry` coverage is 94% and
`signal_bench.telemetry.orchestrator` coverage is 94%. The remaining uncovered
orchestrator lines are defensive branches: state property access, no-task
short-circuit, pending-task timeout logging, final-batch flush, empty-batch
return, and no-run-id guards.
