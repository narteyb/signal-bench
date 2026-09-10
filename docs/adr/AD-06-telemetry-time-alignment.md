# AD-06: Telemetry Time-Alignment Helpers

## Status

Accepted.

## Context

Post 1's headline metric depends on aligning power telemetry samples with model
inference windows. Before T5.3, that alignment lived in consumer code as direct
queries over `telemetry_samples`. That made the edge cases easy to handle
inconsistently: short inference windows can have no samples inside them,
bracketing samples may be needed for interpolation, and partial runs can still
contain useful telemetry for most inference windows.

The schema stores inference timing in `results`: `sequence` is the per-run
inference id, `started_at` is the host/orchestrator clock, and `duration_ms`
defines the completion boundary. Telemetry rows store one capture timestamp per
source metric in `telemetry_samples.timestamp`.

## Decision

Create `signal_bench.analysis.timing` as the single alignment surface. The
helpers accept an explicit SQLAlchemy `Session`, because this repository has no
global database handle and existing synthesis code already passes sessions
explicitly. `samples_for_inference()` returns samples inside the inference
window plus optional bracketing samples. When requested, it inserts synthetic
boundary samples by linear interpolation.

Interpolation is suppressed when the bracketing gap is more than `2x` the
source's inferred sample period. The inferred period is the median gap between
persisted source timestamps. This avoids pretending a real telemetry gap was a
smooth interval.

`inference_coverage()` reports per-window sample presence without mutating the
run-level `telemetry_partial` decision from AD-05. `partial_run_aware=True`
emits `PartialRunWarning` only when a partial run has zero samples inside the
requested inference window. `clock_skew()` is post-hoc analysis, not a new log
event; it classifies paired source timestamps as stable, monotonic, or jittery.

The helpers treat `TelemetrySample.timestamp` as capture time. Current FNB58
parsing does not persist a separate device-clock timestamp, so BLE notification
parse time is the capture proxy. If a later source persists both device time and
host receipt time, the analysis contract should continue exposing capture time
for energy integration and reserve receipt time for transport-latency analysis.

## Alternatives

Leaving alignment inline was rejected because Wh integration, coverage
diagnostics, and future critical-window policy would drift. Adding schema
columns for completed timestamps or source-device timestamps was rejected for
T5.3 because the existing tables already contain enough information for the
helper contract. Higher-order interpolation was rejected because telemetry power
signals are not guaranteed smooth enough to justify it.

## Consequences

Synthesis code should use the analysis helpers instead of querying telemetry
rows directly when it needs aligned samples. Existing run-level Wh values remain
unchanged for complete runs; T5.3 only centralizes how samples are selected.
Future work can build AD-05's deferred critical-window policy by querying
`inference_coverage()` or `samples_for_inference(..., partial_run_aware=True)`.
The explicit session argument is a small ergonomic cost, but it keeps test
fixtures, CLI commands, and future batch analysis jobs in control of database
lifetime and transaction scope.

T8.2 applies the `partial_run_aware=True` opt-in in synthesis export paths.
Captured `PartialRunWarning` entries become per-run
`partial_inference_warnings`, and uncovered per-inference Wh values are
represented as `null` rather than `0`.
