# AD-07: Headline Aggregation Excludes Partial Runs

## Status

Accepted.

## Context

AD-05 defines `runs.telemetry_partial` as a coverage-based trust decision and
records `partial_reasons` for each compromised run. The synthesis layer
previously computed headline latency and Wh/1000 statistics across every run in
a cell, which treated partial and non-partial telemetry as equally reliable.
That is the wrong contract for Signal Report numbers: the headline should
answer what the system measured when telemetry was complete enough to trust.

## Decision

Headline aggregates exclude `telemetry_partial=true` runs. This applies to
median, mean, standard deviation, IQR, hardware-curve latency points, and
Wh/1000 comparison bars. Per-cell detail includes every run and marks partial
runs with `partial=true` plus the persisted `partial_reasons`.

If a cell has runs but every run is partial, the headline value is `null`.
This is distinct from a no-data cell: no-data means the cell was never executed;
all-partial means it ran, but every attempt was compromised. Variance displays
show all runs as points, but the mean line and standard-deviation band use only
the non-partial subset.

## Alternatives

The rejected default was to include partial runs in headline statistics and
only expose their status in detail tables. That keeps more numbers populated,
but it lets a low-coverage run move the published headline.

We also considered a weighted aggregate based on telemetry coverage fraction.
That looks precise but hides a policy choice inside math, and it still lets
partial runs influence the headline. A future diagnostic chart can show coverage
weights explicitly if Phase 5 needs it.

## Consequences

Charts and YAML consumers must handle `null` headline values for all-partial
cells. The smoke harness renders partial variance dots with a distinct marker so
the disclosure is visible without removing data. T3 exporters and downstream
docs should describe the headline as the non-partial aggregate and the detail
table as the complete run record.

T8.2 extends the same null semantics to inference windows inside partial runs:
when telemetry does not cover a window, its per-inference Wh value is `null` and
the run carries `partial_inference_warnings` metadata.
