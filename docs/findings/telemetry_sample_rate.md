# Telemetry Sample Rate Finding (D-SR-01)

## Source Capture

- DB path: `<local-path>`
- Run ID: `019e5741-1557-71f1-a437-2084670f288f`
- Corpus tag: `X`
- Run row window: `2026-05-23 23:52:23.639678` to `2026-05-23 23:52:56.322442`
- Run status: `completed`
- `telemetry_partial`: `false`
- Requested capture duration: `30` seconds

The source windows are slightly shorter than the run row window because the run row is created before source startup and finalized after source shutdown. Sample-rate calculations below use each source's own first and last persisted timestamps.

## R1 Reconciliation

- INA219 adapter: `src/signal_bench/telemetry/sources/ina219.py`, `Ina219Source`, `Ina219Config`
- FNB58 BLE adapter: `src/signal_bench/telemetry/sources/fnirsi.py`, `FnirsiSource`, `FnirsiSourceConfig`
- BME280 adapter: `src/signal_bench/telemetry/sources/bme280.py`, `Bme280Source`, `Bme280Config`
- Async telemetry orchestrator: `src/signal_bench/telemetry/orchestrator.py`
- Schema: `src/signal_bench/schema.py`, table `telemetry_samples`

Collection is source-paced. The telemetry orchestrator starts one async pump per source and persists samples as they arrive; it does not host-poll all sources at a fixed global interval.

`TelemetrySample` is a grouped source sample with one timestamp and a `values` mapping. The database expands that grouped sample into one scalar row per metric. For these sources, each grouped sample has three metrics:

- INA219: `voltage`, `current`, `power`
- FNB58: `voltage`, `current`, `power`
- BME280: `temperature`, `humidity`, `pressure`

The persisted timestamp is wall-clock UTC from the source adapters (`datetime.now(UTC)`), not a persisted monotonic clock. Within this Gate-1 capture, timestamps are strictly increasing per source; no non-positive intervals were observed, so there is no evidence of a wall-clock step inside the measurement window.

## Configured Versus Achieved Rates

| Source | Configured grouped rate | Scalar rows | Distinct sample instants | Metrics per instant | Source window (s) | Mean interval (s) | Effective Hz | p50 interval (s) | p99 interval (s) | Stddev (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| INA219 | 8.0 Hz | 621 | 207 | 3 | 29.940 | 0.145 | 6.881 | 0.125 | 0.373 | 0.080 |
| FNB58 BLE | 4.0 Hz | 363 | 121 | 3 | 30.027 | 0.250 | 3.996 | 0.250 | 0.398 | 0.091 |
| BME280 | 1.0 Hz | 90 | 30 | 3 | 29.041 | 1.001 | 0.999 | 1.005 | 1.026 | 0.020 |

Effective Hz is computed as:

```text
(distinct_sample_count - 1) / (max_timestamp - min_timestamp)
```

## Row Count Reconciliation

The `621` and `363` figures are not sample-instants-per-window. They are scalar metric rows after grouped samples were expanded for storage:

- INA219: `621 rows = 207 grouped sample instants * 3 metrics`
- FNB58 BLE: `363 rows = 121 grouped sample instants * 3 metrics`
- BME280: `90 rows = 30 grouped sample instants * 3 metrics`

Counting scalar rows as sample instants would incorrectly imply about 20 Hz for INA219 and 12 Hz for FNB58 over a 30 second window. The timestamp-derived grouped sample rates are about 6.88 Hz for INA219 and 4.00 Hz for FNB58 BLE.

## Per-Source Interpretation

INA219 is configured to request 8.0 grouped samples per second. The Gate-1 clean capture achieved 6.88 Hz end-to-end through the MCP2221A USB-I2C bridge while all three telemetry sources were active. The achieved rate, not the configured request, is the number to publish for measured methodology.

FNB58 over BLE is configured around the observed 4 Hz measurement-frame cadence. The Gate-1 clean capture achieved 3.996 Hz from real BLE timestamps. It remains a wall-side, window-averaged cross-check and is not the authoritative per-inference energy source.

BME280 was previously configured for 1.0 Hz and achieved 0.999 Hz. The MCU
campaign now uses 0.2 Hz (one grouped read every five seconds), which is
sufficient for ambient context and the session-range gate without competing
with high-rate power attribution.

No adapter in this recon configures explicit oversampling or averaging in the signal-bench source layer; INA219 and BME280 use the Adafruit driver defaults, and FNB58 uses decoded BLE measurement frames from the meter.

## Publishable Methodology Text

Rail-side voltage/current/power was sampled as grouped INA219 readings over an MCP2221A USB-I2C bridge; the adapter requested 8.0 Hz and the Gate-1 clean run achieved 6.88 Hz from 207 distinct sample instants over 29.94 s. Wall-side voltage/current/power was sampled from the FNIRSI FNB58 over BLE at 4.00 Hz, from 121 distinct measurement frames over 30.03 s, and was used only as a window-averaged cross-check. Ambient temperature/humidity/pressure was sampled from the BME280 at 1.00 Hz in that historical Gate-1 run, from 30 distinct readings over 29.04 s; the MCU campaign now uses 0.2 Hz.

## Acceptance Wording

Current protocol wording refers to source-configured coverage. The wording should be interpreted and, in docs, tightened as follows:

> Coverage is computed over grouped telemetry samples, not scalar metric rows. `expected_samples = floor(source.sample_rate_hz * run_duration_s)` uses the source's configured grouped-sample rate; `received_samples` counts persisted grouped samples before expansion into per-metric `telemetry_samples` rows. Source-specific `partial_coverage_threshold` overrides the global threshold when set. Methodology disclosures publish achieved rates from timestamp-derived distinct grouped samples: `(distinct_sample_count - 1) / (max_timestamp - min_timestamp)`.

The current configured rates remain appropriate for coverage expectations:

- INA219: `8.0 Hz`
- FNB58 BLE: `4.0 Hz`
- BME280 historical Gate-1 rate: `1.0 Hz`; MCU campaign rate: `0.2 Hz`

One doc mismatch surfaced during R1: `docs/adr/AD-05-telemetry-partial-data-policy.md` says hardware sources currently use the global partial-data threshold, but the current INA219 and BME280 configs define source-specific `partial_coverage_threshold = 0.75`. This does not change the sample-rate finding, but the ADR should be updated in a separate documentation cleanup.

## Re-Capture Decision

No re-capture needed.

The existing Gate-1 clean capture has per-source timestamps, enough distinct samples over about 30 seconds to characterize each source, strict per-source timestamp ordering, and `telemetry_partial=false`. The ambiguity came from counting scalar metric rows as sample instants, not from missing data.
