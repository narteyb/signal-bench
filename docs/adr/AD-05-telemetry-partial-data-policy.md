# AD-05: Telemetry Partial-Data Policy

## Status

Accepted. Supersedes AD-03's strict mid-run disconnect partial policy for the
async orchestrator.

## Context

AD-03 marked a run partial as soon as any source disconnected or emitted
malformed data. That strict rule was simple, but it over-flags real hardware
runs: a short BLE interruption during a long measurement should be visible in
logs without automatically invalidating the run. T5.1 added structured events
for the symptoms. T5.2 decides the final database flag.

## Decision

The async orchestrator uses a coverage-based run-end policy. Coverage is
computed over grouped `TelemetrySample` instants, not the scalar
`telemetry_samples` rows produced after metric expansion. For each source,
`expected_samples = floor(sample_rate_hz * run_duration_s)`, and
`coverage_fraction = received_grouped_samples / expected_samples`. A run is
marked `telemetry_partial=true` if any source's coverage is below
`SIGNAL_BENCH_PARTIAL_COVERAGE_THRESHOLD`, defaulting to `0.90`. Expected
samples are an integer count, and the implementation allows a two-sample grace
once a source expects at least twenty samples. That keeps short smoke runs from
being marked partial because of scheduler jitter while preserving the 90% rule
for real measurement windows.

The threshold is validated as `0.0 < threshold <= 1.0`. Sources may override the
global threshold with `partial_coverage_threshold`; the real INA219 and BME280
hardware sources use `0.85` for the MCU campaign, while sources without an
override use the global default. The campaign threshold is kept separate from
the global default so a campaign can require a stricter minimum without
changing unrelated telemetry consumers.
The final decision emits `telemetry_partial_decided` with per-source coverage,
sample counts, and reason strings. The `runs` table stores those reason strings
in `partial_reasons`, for example: `fnb58: coverage=72%, threshold=90%,
samples=1080/1500`.

Coverage is computed from grouped samples that reached persistence, not samples
a device may have attempted to produce and not the expanded per-metric row
count. That makes the policy match downstream analysis: T3 and Post 1 can only
integrate, aggregate, or disclose data that is actually present in the database.
A source that produces data but loses it in a local queue still has reduced
coverage because those samples never become usable evidence.

Publication methodology reports achieved sample rates from persisted grouped
timestamps using `(distinct_sample_count - 1) / (max_timestamp - min_timestamp)`.
That rate is separate from the configured `sample_rate_hz` used for coverage
expectations.

Database writer failure is partial because data was lost before persistence.
Writer lag alone is not partial because back-pressure delays samples rather
than dropping them. Source-local drops reduce persisted coverage naturally; if
enough samples are lost, the coverage rule marks the run partial.

## Alternatives

Strict policy was rejected because transient disconnects would discard otherwise
usable data. Duration-based policy was rejected because "down for 5%" is less
directly tied to what the analysis actually has in hand. Coverage plus critical
window was deferred until T5.3 defines inference windows; it may later extend
this policy without replacing its coverage foundation.

## Consequences

Phase 5 gets a tunable, numeric trust signal rather than a brittle binary
reaction to any source failure. T3 synthesis should exclude
`telemetry_partial=true` runs from headline aggregates while still showing them
in per-cell detail with `partial_reasons`. Operators can keep using T5.1 events
as leading indicators during a run, but the database flag is the final
coverage-based decision after shutdown.

The policy is intentionally not a publication rule. It answers whether telemetry
coverage was complete enough for a run to be trusted by default. Editorial and
synthesis layers may still show partial runs for transparency, rerun them, or
exclude them from headline statistics depending on the report's needs.
