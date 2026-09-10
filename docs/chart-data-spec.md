# Chart Data Spec

T3.5 turns exported matrix YAML into Chart.js configuration JSON for Post 1.
The input is `MatrixData` from T3.4, not the benchmark database. This keeps
chart preparation deterministic: T3.4 owns SQL and measurement extraction,
while T3.5 owns display-oriented aggregation and serialization.

## Aggregation

Headline charts use median-of-runs. For latency, each run contributes its
`latency_stats.median_us`; the cell value is the median of those run medians.
For energy, each run contributes `energy_stats.wh_per_1000`; the chart converts
that value to mWh for readability and again takes the median across runs. Cells
with no usable runs emit `null`, which Chart.js treats as a gap. This avoids
promoting the most recent run by accident and makes isolated re-run spikes less
likely to dominate the narrative.

## Hardware Curve

`build_hardware_curve()` returns a Chart.js `line` config. The X axis is target
capability order: F401RE, Nano 33, ESP32-S3, Pi 5, Jetson Orin Nano, M1 Max,
Modal A10G. Each task is one dataset. The Y axis is logarithmic median latency
in microseconds because MCU, SBC, local, and cloud targets can differ by orders
of magnitude.

## Wh Comparison

`build_wh_comparison()` returns a grouped `bar` config with the same target
ordering and one dataset per task. Values are mWh per 1000 inferences, derived
from T3.4's run-level `wh_per_1000` field. The Y axis is logarithmic for the
same reason as latency: power and runtime differences can span much more than a
linear chart can show clearly.

## Variance Illustration

`build_variance_illustration()` defaults to KWS on Pi 5. It preserves repeat
spread instead of collapsing to one number: each run is a bar whose `y` is
median latency, with `yMin`, `yMax`, and `runId` included in the data object for
tooltips or a future error-bar plugin. Chart.js renders the median value even
without plugins; the extra fields remain available to blog code.

## Variance Strip

`build_variance_strip()` returns a Chart.js v4 `scatter` config with three
logical dataset layers per `(target, task)` cell, keyed by a `role` field on
each dataset object so the consumer composes them without relying on dataset
ordering:

1. **Per-run dots** (`role: "runs"`): one scatter point per individual
   measurement, X positioned at the cell label, Y equal to the run's
   `latency_stats.median_us`.
2. **Cell mean** (`role: "mean"`): one point per cell at the arithmetic mean
   of non-partial run latencies (via `cell_headline(..., statistic="mean")`
   in `signal_bench.synth._partial`).
3. **±1 stddev band** (`role: "stddev_band"`): one point per cell carrying
   `yMin` / `yMax` for the sample-standard-deviation band (Bessel's
   correction, `statistics.stdev` with `ddof=1`). Single-run cells emit
   `yMin = yMax = None` since stddev is undefined for n=1 under Bessel.

The builder accepts optional `tier` and `task` keyword arguments to filter
to a hardware-tier subset (e.g., `tier="tier1"` for the three MCU targets:
F401RE, Nano 33, ESP32-S3) and / or a single task. Cells are ordered
task-major (TASK_ORDER: kws → ic → ad), target-minor (TARGET_ORDER filtered
by tier). Per-cell metadata lives in the top-level `meta.cells` array as a
parallel structure to `build_variance_illustration`'s `meta` field, carrying
`nTotal`, `nPartial`, `headlineBasis`, `partialInferenceCount`, and the
computed `mean` and `stddev`.

## Latency unit convention

Producer-side latency values are emitted in microseconds (μs) for precision
and for consistency across all `chart_data.py` builders
(`build_hardware_curve`, `build_variance_illustration`,
`build_variance_strip`). Consumer-side renderers display values in
user-readable units per chart context: Post 1 charts display milliseconds
(ms) for human readability at the typical MCU / SBC inference magnitude
range. The producer emits raw numerical values without unit metadata in
the data points themselves; consumers convert at render time. Axis titles
in each chart's spec name the display unit explicitly.

## Files And Styling

`write_chart_json_files()` writes six files. The legacy three cover the
full seven-target hardware curve and Wh comparison plus the default
variance illustration: `hardware-curve.json`, `wh-comparison.json`,
`variance-illustration.json`. The Post 1 Tier 1 variants restrict to the
MCU subset (F401RE, Nano 33, ESP32-S3) and the variance-strip variant uses
the three-layer scatter shape from the Variance Strip section above:
`hardware-curve-tier1.json`, `wh-comparison-tier1.json`,
`variance-strip-tier1.json`. All six use Chart.js v4-style
`{type, data, options}` objects. T3.5 deliberately does not hardcode a
color palette; the blog can apply brand styling at render time, or
Chart.js can fall back to defaults for the demo.

Accuracy charts are out of scope until Phase 5 produces accuracy data.

## Demo Output

The integration demo writes a standalone HTML file under
`tests/integration/synth/_demo.html`. It loads Chart.js from the jsDelivr CDN
and embeds synthetic chart configs inline. The file is not a production blog
template; it is a smoke artifact for manually checking that the generated JSON
has the expected top-level Chart.js shape and can be rendered by a browser. The
actual Post 1 page can use the same JSON files through the blog's eventual
`data-chart` or static asset pipeline.
