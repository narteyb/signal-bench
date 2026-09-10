# AD-04: Telemetry Structured Logging

## Status

Accepted.

## Context

AD-03 defines the async telemetry orchestrator, source lifecycle, grouped sample
fanout, and partial-run policy. It does not define how Phase 5 operators should
debug failures while real hardware is attached. Raw tracebacks are not enough:
a BLE disconnect, a source-local queue drop, and a SQLite writer stall all need
different remediation, and each needs run/source context.

## Decision

Telemetry components emit structured JSON-line log events through stdlib
`logging`. The telemetry package owns one logging helper module,
`signal_bench.telemetry.logging`, which installs a JSON formatter and exposes
`get_logger()` plus `emit_event()`.

Each event carries:

- `event`: stable snake_case event name
- `source`: source name or `orchestrator`
- `run_id`: active run id, or `null` before a run is known
- `at_ts`: orchestrator-side UTC timestamp
- `context`: event-specific fields

Logs go to stderr by default. `SIGNAL_BENCH_LOG_LEVEL` controls level and
defaults to `INFO`. `SIGNAL_BENCH_LOG_DEST` defaults to `stderr` and may be set
to a file path for Phase 5 run capture.

The orchestrator also tracks lightweight health signals: rolling five-second
sample rate, source silence, queue fill fraction, stale/future timestamps, and
cross-source clock skew. These checks do not change the AD-03 persistence model;
they add observability around it.

## Consequences

- Phase 5 debugging can grep or `jq` run logs without reading orchestrator code.
- Event names become a small API. Renames should be treated as compatibility
  breaks for analysis scripts.
- No new dependency is added. If the project later adopts `structlog`, this
  decision can be revisited without changing the event taxonomy.
- The existing stdout CLI summaries stay human-readable; structured logs remain
  on stderr or a configured file.

## Alternatives Considered

### Plain Text Logging

Plain text is readable, but it forces Phase 5 analysis scripts to parse message
strings. The structured event payload is more stable and easier to query.

### `structlog`

`structlog` would provide a cleaner binding API, but it is not currently a
project dependency. The stdlib is sufficient for T5.1's needs.

### Source-Only Logging

Sources see hardware-specific failures, but the orchestrator owns run ids,
partial policy, queue state, and database writes. Logging only from sources
would miss the context needed to reconstruct a failed run.
