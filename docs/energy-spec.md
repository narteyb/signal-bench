# Energy Metric Spec

T3.3 defines Signal Report Post 1's headline energy metric: watt-hours per
1000 measured inferences. The value is a run-level scalar, not a per-inference
distribution. The FNB58 BLE path advertises notifications at roughly 10 Hz, but
live voltage/current/power measurement frames arrive at roughly 4 Hz on the
validated bench meter firmware. SBC and cloud targets can complete many
inferences between adjacent power samples. The only defensible computation is
therefore to integrate power over the measured run window and normalize by the
number of completed measurement inferences.

## Computation

`compute_energy()` accepts sorted `(t_seconds, power_watts)` pairs. Time is
relative to run start; the DB export layer must convert absolute telemetry
timestamps before calling it. Energy is integrated with the trapezoid rule:
each adjacent pair contributes `((p0 + p1) / 2) * (t1 - t0)` joules. Joules are
used internally because they are SI units; `EnergyStats.total_wh` converts at
the boundary with `Wh = J / 3600`.

`wh_per_1000(stats, inference_count)` returns:

```text
(stats.total_wh / inference_count) * 1000
```

For a constant 5 W load over 30 seconds, total energy is 150 J, or 41.67 mWh.
If that run completed 100 measured inferences, the normalized metric is 416.67
mWh per 1000 inferences.

## Coverage

`EnergyStats.telemetry_coverage` reports the fraction of the run duration
covered by available power samples. When a run duration is supplied, coverage is
`(last_sample_t - first_sample_t) / run_duration_s`, capped at 1.0. Low coverage
does not change the integrated energy and the function does not extrapolate
beyond the sample window. Rendering and aggregation layers should flag low
coverage as a data-quality issue.

## Edge Cases

At least two samples are required for trapezoidal integration. Runs with 2-9
samples still compute but carry a warning because they are too short for stable
energy measurement at the expected FNB58 measurement-frame rate. Negative power values are
clamped to 0 W with a warning; they are treated as meter noise, not energy
generation. Zero inferences returns infinity because energy without completed
inferences is not a meaningful normalized result. Negative inference counts or
negative energy totals raise `ValueError`.

## MLPerf Comparison

MLPerf Tiny measures latency and quality and enables optional energy
benchmarking. Its public Tiny results describe power columns as system power
for server/offline scenarios or energy per stream for single-stream scenarios.
Signal-bench uses the same basic idea of measured system energy during the
benchmark window, but normalizes it as Wh/1000 inferences so all Post 1 cells
share one readable matrix unit across MCU, SBC, local, and cloud targets while
keeping the underlying integration auditable.
