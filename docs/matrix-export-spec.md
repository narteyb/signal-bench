# Matrix Export Spec

T3.4 defines the bridge from benchmark storage to report-ready data. The
exporter reads a validated `MatrixConfig`, queries the SQLite ORM tables for
matching runs, computes run-level timing and energy summaries, and writes a
schema-versioned YAML document. The matrix config is the driver: cells that are
present in the database but absent from the config are ignored, while configured
cells with no matching runs are still emitted with `status: "no_data"`.

## Output Shape

The output document has `schema_version: 1`, `matrix_name`, `generated_at`,
`generated_from_runs`, and `cells`. Each cell contains `task`, `target`,
`status`, and a `runs` list. Run entries preserve the source run ID, start time,
duration, iteration counts, model hash, quantization, telemetry partial flags,
latency stats, energy stats, and warnings. This structure extends the matrix
config with measurements without changing the config itself.

## Run Handling

The exporter includes every run matching a configured `(task, target)` pair.
Multiple runs per cell are not collapsed. T3.5 can later choose a canonical run,
use median-of-runs, or show repeats explicitly. Incomplete runs are included
with their database `status`; if `finished_at` is null, duration and energy
stats are omitted and a warning explains why. Runs with no `Result` rows after
warmup exclusion remain in the file as well. Their latency stats are null, and
their warnings make the missing measurement data visible instead of silently
turning the cell into `no_data`.

## Computed Fields

Latency comes from `Result.duration_ms`, ordered by `sequence`. The first
`Run.warmup_count` rows are excluded before calling T3.2's
`compute_variance()`. Exported latency fields are in microseconds:
`mean_us`, `median_us`, `p95_us`, `p99_us`, `stddev_us`, and
`variance_pct`.

Energy uses T3.3's `compute_energy()` and `wh_per_1000()`. The query filters
telemetry samples to `source="fnb58"` and `metric="power"` by default, then
converts absolute timestamps to seconds since `Run.started_at`. No
extrapolation is performed. If telemetry covers only part of a run,
`telemetry_coverage` reflects that gap and the renderer can flag the cell.

## Time And Quality Flags

SQLite may return timezone-naive datetimes, so the exporter treats naive values
as UTC and normalizes aware values to UTC before subtraction or YAML
serialization. `Run.telemetry_partial` and `telemetry_partial_sources` are
copied verbatim into each run entry. The exporter does not decide whether a
partial run is publishable; it only preserves the quality signal.

## Future Evolution

Schema version 2 can add adapter-provided accuracy summaries, live-input
variant fields, or precomputed cross-run rollups. T3.4 intentionally avoids
those decisions. Its contract is raw-but-structured matrix data that downstream
rendering and CLI layers can consume without querying the benchmark database
again.
