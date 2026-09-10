# Telemetry Observability

The async telemetry orchestrator is easiest to debug when each lifecycle and
failure condition is emitted as a structured event. Phase 5 runs may fail
because of BLE loss, malformed samples, a slow SQLite writer, or a source that
quietly stops. JSON-line logs make those conditions visible without requiring a
debugger or a rerun.

Telemetry logs are newline-delimited JSON objects on stderr by default. Each
event has a stable top-level shape: `event`, `source`, `run_id`, `at_ts`, and an
event-specific `context` object. The formatter also includes `level` and
`logger` for filtering.

Example lines:

```json
{"at_ts":"2026-05-11T16:20:00.000Z","context":{"source_count":3,"sources":["fnb58","mock_ina219_main","mock_bme280_lab"]},"event":"run_started","level":"INFO","logger":"signal_bench.telemetry.orchestrator","run_id":"019e1090-a1e9-77a2-bc89-dc86d48499fd","source":"orchestrator"}
{"at_ts":"2026-05-11T16:20:03.000Z","context":{"expected_hz":10.0,"observed_hz":3.2,"threshold_hz":5.0,"window_s":5.0},"event":"sample_rate_below_threshold","level":"WARNING","logger":"signal_bench.telemetry.orchestrator","run_id":"019e1090-a1e9-77a2-bc89-dc86d48499fd","source":"fnb58"}
{"at_ts":"2026-05-11T16:20:05.000Z","context":{"error_class":"SourceDisconnectError","message":"FNB58 connection lost"},"event":"source_disconnected","level":"ERROR","logger":"signal_bench.telemetry.orchestrator","run_id":"019e1090-a1e9-77a2-bc89-dc86d48499fd","source":"fnb58"}
```

## Event Catalog

| Event | Level | Context fields | Meaning |
|---|---:|---|---|
| `run_started` | INFO | `source_count`, `sources`, `queue_maxsize`, `batch_size` | A telemetry run began. |
| `run_stopping` | INFO | none | Shutdown has started. |
| `run_completed` | INFO | `samples_written`, `rows_written`, `failed_sources`, `partial` | Shutdown completed without orchestrator-level failure. |
| `run_failed` | ERROR | `samples_written`, `rows_written`, `failed_sources`, `error_class`, `message` | The run ended with an orchestrator-level failure. |
| `run_start_rejected` | ERROR | `reason` | Caller attempted to start while another run was active. |
| `source_started` | INFO | `sample_rate_hz` | A source started successfully. |
| `source_stopped` | INFO | none | A source stopped cleanly. |
| `source_start_failed` | ERROR | `error_class`, `message`, `failed_sources` | One or more sources failed during startup. |
| `source_disconnected` | ERROR | `reason`, or `error_class` and `message` | A source disconnected or stopped emitting samples. |
| `source_data_error` | ERROR | `error_class`, `message` | A source emitted malformed data after startup. |
| `source_telemetry_error` | ERROR | `error_class`, `message` | A typed telemetry error occurred. |
| `source_unhandled_exception` | ERROR | `error_class`, `message` | A source raised an unexpected exception. |
| `source_stopped_unexpectedly` | WARNING | none | A source iterator ended before shutdown. |
| `source_task_stop_timeout` | WARNING | `task_name` | A source task did not stop within the shutdown timeout. |
| `orchestrator_teardown_failed` | ERROR | `reason`, optional `error_class`, `message` | Source cleanup timed out or failed. |
| `partial_data_threshold_crossed` | WARNING | `failed_sources`, `source_count` | A real-time symptom indicates the run may become partial. The final flag is decided at run end. |
| `telemetry_partial_decided` | INFO | `partial`, `criterion`, `threshold_frac`, `per_source_coverage`, `expected_samples`, `received_samples`, `reasons` | Run-end coverage policy decision for `runs.telemetry_partial`. |
| `all_sources_failed` | ERROR | `failed_sources` | No telemetry source remains healthy. |
| `db_write_lagging` | WARNING | `queue_size`, `queue_maxsize`, `queue_fraction`, `threshold_fraction` | The writer queue is near capacity. |
| `db_write_failed` | ERROR | `error_class`, `message`, `batch_size`, `queue_size` | The writer failed to persist telemetry rows. |
| `queue_overflow_dropping_sample` | ERROR | `queue_maxsize` | A source-local queue dropped a sample. |
| `queue_drained_after_writer_failure` | WARNING | `drained_samples` | Pending samples were discarded after writer failure. |
| `sample_rate_below_threshold` | WARNING | `expected_hz`, `observed_hz`, `threshold_hz`, `window_s`, `duration_s` | Rolling sample rate was below 50% of expected long enough to matter. |
| `sample_timestamp_invalid` | WARNING | `reason`, `timestamp`, optional `age_s` | A sample timestamp was naive or implausibly future-dated. |
| `sample_timestamp_stale` | WARNING | `age_s`, `threshold_s`, `timestamp` | A sample timestamp was too old. |
| `clock_skew_detected` | WARNING | `skew_s`, `threshold_s`, `sources` | Source timestamps diverged beyond the skew threshold. |
| `source_sample_malformed` | WARNING | `consecutive_malformed` | FNB58 packet parsing rejected a malformed notification. Well-formed non-measurement status frames are ignored. |
| `source_reconnect_not_implemented` | WARNING | `configured_attempts` | FNB58 reconnect was requested but is not implemented. |
| `source_disconnect_cleanup_failed` | DEBUG | `error_class` | Best-effort BLE disconnect cleanup failed. |
| `sample_received` | DEBUG | `metric_count`, `queue_size` | A grouped sample was accepted from a source. |
| `db_batch_written` | DEBUG | `sample_count`, `row_count` | A writer batch was persisted. |

## Reading Logs

Common Phase 5 checks:

```bash
# Did the BLE meter drop?
grep '"event":"source_disconnected"' run.log | jq 'select(.source=="fnb58")'

# What was the worst writer lag?
grep '"event":"db_write_lagging"' run.log | jq '.context.queue_fraction' | sort -nr | head

# Why was the run marked partial?
grep '"event":"telemetry_partial_decided"' run.log | jq '.context.reasons'

# Were timestamps suspect?
grep -E '"event":"(sample_timestamp_invalid|sample_timestamp_stale|clock_skew_detected)"' run.log
```

## Environment Variables

`SIGNAL_BENCH_LOG_LEVEL` controls the telemetry logger level. It defaults to
`INFO`; set it to `DEBUG` for per-sample and per-batch events.

`SIGNAL_BENCH_LOG_DEST` controls destination. It defaults to `stderr`. Set it to
a file path, for example `SIGNAL_BENCH_LOG_DEST=phase5-run.jsonl`, to write
JSON lines to a file.

`SIGNAL_BENCH_PARTIAL_COVERAGE_THRESHOLD` controls the run-end partial-data
coverage threshold. It defaults to `0.90`; values must satisfy
`0.0 < threshold <= 1.0`. The policy allows a two-sample grace for short
healthy runs once a source expects at least twenty samples.

## Reading Per-Inference Power From Telemetry

Use `signal_bench.analysis.timing` when a report or analysis needs telemetry
samples aligned to one inference window. The helpers use persisted capture
timestamps from `telemetry_samples.timestamp`; for FNB58 this is the timestamp
attached when the BLE notification is parsed, and for I2C sources it is the
host-side read time.

```python
from signal_bench.analysis.timing import samples_for_inference

samples = samples_for_inference(
    db_session,
    run_id=run.run_id,
    inference_id=42,
    source="fnb58",
    include_bracketing=True,
    interpolate_at_boundaries=True,
    partial_run_aware=True,
)
# Pass `samples` to the Wh integration path.
```

`include_bracketing=True` is the right default for power integration because
TinyML inference windows can be shorter than the telemetry sample period.
`interpolate_at_boundaries=True` adds synthetic samples at exact inference
boundaries when the adjacent source samples are close enough to trust. Use
`partial_run_aware=True` for aggregate analysis so missing samples inside a
partial run emit `PartialRunWarning`; leave it off for raw inspection.

## How Partial Runs Flow Through Synthesis

Partial detection is decided by the telemetry layer at run end. The orchestrator
sets `runs.telemetry_partial` and persists `partial_reasons`; synthesis consumes
those fields without redefining the policy.

Headline synthesis excludes partial runs from aggregates. Hardware-curve latency
points, Wh/1000 bars, mean lines, standard-deviation bands, medians, means, and
IQRs are computed from non-partial runs only. If every run in a cell is partial,
the headline value is `null`, not zero and not a best-effort partial aggregate.

Per-cell detail still includes every run. Partial runs carry `partial=true` and
their `partial_reasons`, and the Post 1 smoke harness renders them as distinct
variance markers. This keeps the headline clean while preserving the complete
record a reader needs to audit the measurement.

When a Phase 5 chart caption encounters an all-partial cell, call it out
directly: all runs in that cell were partial, so the headline is blank and the
detail table carries the reasons.

Per-inference attribution opts into `PartialRunWarning` when it scans partial
runs. If a partial run has an inference window with zero source samples, the
exporter captures the warning as `partial_inference_warnings` on that run and
adds the count to the cell detail. A per-inference Wh value for that window is
`null`: it means telemetry did not cover the window, not that the inference used
zero energy. The CLI prints a `Partial inference windows` line only when this
count is non-zero, and the Post 1 smoke harness renders all-null cells with a
telemetry-gap annotation.
