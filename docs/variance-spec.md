# Variance Analysis Spec

T3.2 defines a pure statistics layer for post-warmup measurement samples. It
does not query the database, slice warmup rows, compute energy, or render
tables. Callers pass a sequence of finite numeric samples, usually
per-inference latency in milliseconds, and receive a `VarianceStats` summary.
This keeps the statistics layer reusable for latency, power, accuracy, and
future scalar measurements. DB-specific concerns, including selecting rows,
dropping warmup iterations, and grouping by matrix cell, belong to later T3
aggregation work.

## Metrics

The Post 1 metric set is hardcoded: `mean`, `median`, `p95`, `p99`, `stddev`,
`variance_pct`, `min`, and `max`. `mean` is the arithmetic average and remains
the headline value for compact tables. `median` gives a robust middle value
when latency is skewed. `p95` and `p99` expose tail behavior, which is often
more important than mean latency on multitasking hosts. `stddev` is sample
standard deviation (`ddof=1`), because 100 inferences are a sample of possible
runtime behavior, not the full population. `variance_pct` is coefficient of
variation: `100 * stddev / abs(mean)`.

The percentile implementation uses linear interpolation over sorted samples.
This keeps behavior deterministic without depending on NumPy-specific
percentile defaults.

## Outlier Policies

Outlier detection runs before stats are computed. `n_samples` is the cleaned
sample count; `n_outliers` records how many values were removed.

`iqr` is the default policy. It removes values below `Q1 - 1.5 * IQR` or above
`Q3 + 1.5 * IQR`. This is robust for benchmark samples without assuming normal
data. `zscore` removes values with absolute z-score greater than `3`, useful
when a metric is known to be near-normal. `none` keeps every sample and exists
for transparency mode or debugging raw measurements.

Outlier detection is skipped for fewer than four samples because quartiles and
z-scores are not meaningful at that size.

## Edge Cases

Empty input is a programming error and raises `ValueError`. A single sample
returns degenerate stats: mean, median, percentiles, min, and max equal the
sample; `stddev` is `0`; `variance_pct` is `nan` because coefficient of
variation is undefined for `n < 2`. If the mean is zero for two or more samples,
`variance_pct` is `inf`. Non-finite samples (`nan` or infinities) are rejected
before any policy runs.

## Examples

`compute_variance([100, 101, 99, 100, 1000])` with `iqr` removes `1000` before
computing stats. With `none`, the same outlier remains and inflates the mean and
tail percentiles. Future schema versions may make the metric set configurable;
Post 1 keeps it fixed so renderers and report text can depend on stable fields.
When debugging a surprising report value, compare `n_outliers`, `min`, and
`max` first; they usually reveal whether a tail sample was retained or removed.
