# Report 1 retrospective findings

## Executive finding

The records support descriptive session-level reporting, not a cross-board energy conclusion at the strength of Report No. 1's wording. The published medians place Nano 33 below F401RE and ESP32-S3 on all three task rows, but the published sessions do not provide three boundary-matched sessions on both sides of any board comparison. The energy-winner statement is therefore an unadjusted description of the published medians, not a supported general claim that Nano 33 wins energy across every measured task.

## Reproduction

The script is `scripts/analyze_post1.py`. It reads `content/signal-reports/2026-05-28-tinyml-reality-check-data.yml` and these run-record databases:

- `data/p3_mcu_matrix.db`
- `data/scratch/p3_mcu_matrix.reference-scratch.20260524-215641.db`
- `data/scratch/p3_mcu_matrix.esp-attempt.20260524-220230.db`
- `data/scratch/p3_mcu_matrix.esp-pre-fnb-patch.20260524-220931.db`
- `data/launch_tier_reproduction.db`

The deterministic command is `uv run python scripts/analyze_post1.py`; no random sampling or random seed is used. The generated files are `session_table.md`, `estimates.md`, and this document.

## Exclusion rules

Rules were fixed from recorded run metadata before deriving the estimates. No measured latency, energy, ambient value, or other numeric result is used as an exclusion condition.

- A record from a scratch database is preliminary scratch provenance and is excluded from the published set.
- A record whose corpus is not N3 or whose recorded protocol is not `n3` is excluded as a different or unrecorded evaluation protocol.
- A record with a non-completed recorded status is excluded as failed or incomplete.
- A record marked `repeat_quarantined` is excluded as a quarantined repeat.
- A record marked `telemetry_partial` is excluded from the boundary-consistent published session set.
- A completed N3 record that passes those checks but is not one of the three run IDs in the published-cell manifest is outside this retrospective's published subset.

The selected 27 sessions are completed N3 records with no partial telemetry or repeat-quarantine marker. Excluded input records by primary reason are:

| Primary reason | Records |
|---|---:|
| different or unrecorded evaluation protocol | 22 |
| outside the published three-session selection | 6 |
| preliminary scratch record | 9 |
| recorded partial telemetry | 3 |
| recorded repeat quarantine | 11 |
| recorded status=failed | 1 |

The complete excluded-record list is included below so the scope is auditable.

| Cell/source | Run ID | Status | Reason |
|---|---|---|---|
| ad/esp32s3 (scratch) | `019e5d70-b28c-72f2-bd2a-1c186710723f` | completed | preliminary scratch record |
| ad/esp32s3 (scratch) | `019e5d81-fc94-75c3-aafd-28bba9de0569` | completed | preliminary scratch record; recorded partial telemetry |
| ad/esp32s3 (scratch) | `019e5d88-6cbc-70b0-b28b-c033bd2a08c6` | completed | preliminary scratch record |
| ad/esp32s3 (canonical) | `019e6532-b4fd-7310-8cf7-4eda7c26f834` | failed | recorded status=failed |
| ad/esp32s3 (canonical) | `019f1b27-5278-71d3-a810-a67924e18b9d` | completed | different or unrecorded evaluation protocol |
| ad/f401re (canonical) | `019e5db6-a631-7210-85dd-7cc33f0e0049` | completed | recorded repeat quarantine; recorded partial telemetry |
| ad/f401re (canonical) | `019e5dc5-11f9-7a41-8fd5-543d80de7eaa` | completed | recorded repeat quarantine |
| ad/f401re (canonical) | `019e71d6-2d18-70b2-aef5-0d594ad79a56` | completed | recorded repeat quarantine |
| ad/f401re (canonical) | `019e71dd-d72d-74d1-9087-1efa126593cb` | completed | recorded repeat quarantine |
| ad/f401re (canonical) | `019f1ad5-ac11-7d73-bee5-7d49296328b0` | completed | different or unrecorded evaluation protocol |
| ad/f401re (canonical) | `019f3675-53cc-7a92-860a-f0e60f02f711` | completed | recorded partial telemetry |
| ad/nano33 (canonical) | `019e7543-37c3-7e32-bd60-339408178788` | completed | outside the published three-session selection |
| ad/nano33 (canonical) | `019f1baf-6b36-7d62-842c-1e1eb719b3dc` | completed | different or unrecorded evaluation protocol |
| ad/nano33 (canonical) | `019f1bf3-5e03-7822-a65f-5b4eab5b88cf` | failed | different or unrecorded evaluation protocol; recorded status=failed |
| ad/nano33 (canonical) | `019f1bfb-8dbb-74c3-9beb-60e625e42deb` | completed | different or unrecorded evaluation protocol |
| ic/esp32s3 (scratch) | `019e5d6f-4eed-73c2-8d0f-95150ef958a7` | completed | preliminary scratch record |
| ic/esp32s3 (scratch) | `019e5d80-801f-75a2-a740-2f8d27174cdf` | completed | preliminary scratch record |
| ic/esp32s3 (scratch) | `019e5d86-53cb-7b70-a34f-5c0a711f08ef` | completed | preliminary scratch record |
| ic/f401re (canonical) | `019e5db4-e375-7942-9182-e4fef42ce9c7` | completed | outside the published three-session selection |
| ic/nano33 (canonical) | `019e7545-f8a5-75e0-a20d-857ae690429e` | completed | outside the published three-session selection |
| kws/esp32s3 (scratch) | `019e5d6d-c417-7842-be92-fb7ea2a5539e` | completed | preliminary scratch record |
| kws/esp32s3 (scratch) | `019e5d7f-0d12-72f0-b07b-7a384b978c9b` | completed | preliminary scratch record |
| kws/esp32s3 (scratch) | `019e5d84-434f-7742-bd12-339e977ab46e` | completed | preliminary scratch record |
| kws/esp32s3 (canonical) | `019f1b19-4353-7943-9502-72e16d1e74eb` | completed | different or unrecorded evaluation protocol |
| kws/esp32s3 (canonical) | `019f785e-696c-7811-ad2a-ba508aa844ef` | completed | different or unrecorded evaluation protocol |
| kws/esp32s3 (canonical) | `019f789c-2e0f-7f72-b6b0-15b19c8100a3` | completed | different or unrecorded evaluation protocol |
| kws/f401re (canonical) | `019e5db3-0d4d-72e1-8033-380875e45cf3` | completed | recorded repeat quarantine |
| kws/f401re (canonical) | `019e71d5-1aba-7d52-870e-36d09b4e05a3` | completed | recorded partial telemetry |
| kws/f401re (canonical) | `019e71d7-9146-7c70-9034-a703f581fd72` | completed | recorded repeat quarantine |
| kws/f401re (canonical) | `019e71df-33a5-7543-b033-19e93aa72de1` | completed | recorded repeat quarantine |
| kws/f401re (canonical) | `019f1b03-be72-74b2-8498-bacb755ae407` | completed | different or unrecorded evaluation protocol |
| kws/f401re (canonical) | `019f3d83-32b9-74d0-b483-b8f81725204e` | completed | recorded repeat quarantine; recorded partial telemetry |
| kws/f401re (canonical) | `019f3d84-ab01-7533-b0f0-d96b93e2a480` | completed | recorded repeat quarantine; recorded partial telemetry |
| kws/f401re (canonical) | `019f3d86-cc72-7831-bac5-f89d8aa87442` | completed | recorded repeat quarantine; recorded partial telemetry |
| kws/f401re (canonical) | `019f3d88-5d8a-75d1-b212-6cf0e48e0efb` | completed | recorded repeat quarantine; recorded partial telemetry |
| kws/f401re (canonical) | `019f7860-eabc-7e41-bb5a-75187e046e77` | completed | different or unrecorded evaluation protocol |
| kws/f401re (canonical) | `019f7896-c91b-7b03-a1e5-252cc2f47d0f` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019e5da5-52ee-7d03-800e-9737850b6d96` | completed | outside the published three-session selection |
| kws/nano33 (canonical) | `019e7548-0873-7571-99dd-e67e5eb23723` | completed | outside the published three-session selection |
| kws/nano33 (canonical) | `019e755c-e759-7ff3-8303-c589cf777493` | completed | outside the published three-session selection |
| kws/nano33 (canonical) | `019e7564-8561-7cc3-b6fb-9359503a5a88` | completed | recorded partial telemetry |
| kws/nano33 (canonical) | `019f1b97-b48a-7a73-9afb-9fe4664e9b72` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f1c3e-bede-7e12-8383-c35fe1f5aa8f` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f715c-9cc3-7203-b3c4-1a8464cb6d42` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f715e-5511-74d2-bff6-7eb82d54566a` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f7394-5bb0-7962-b42d-4dc6e7662484` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f7397-f5b0-7852-b94a-4ed3eb4718a7` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f73ae-bff2-74d3-9c2a-73c1a393b2ab` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f73b0-6e0f-79d0-a2ab-0d11a485324a` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f785a-ac7c-7270-814a-88418a0b56e8` | completed | different or unrecorded evaluation protocol |
| kws/nano33 (canonical) | `019f789f-f2a4-7a61-a7db-5ad0164e2f54` | completed | different or unrecorded evaluation protocol |
| telemetry-test/telemetry-test (canonical) | `019e758a-9b42-71f3-b3c9-0cfa32c1591c` | completed | different or unrecorded evaluation protocol; recorded partial telemetry |

## Boundary grouping

The grouping is performed before any ratio calculation. A documented boundary is taken from `Run.extra.boundary_state`. When that field is absent, the retained power-source set distinguishes two-instrument capture from single-instrument capture, while preserving that the boundary itself was unrecorded.

| Cell | Boundary counts | Estimate eligibility |
|---|---|---|
| kws/f401re | `documented-full-board`=3 | at least three in one state |
| kws/nano33 | `two-instrument-unrecorded`=1, `single-instrument-unrecorded`=2 | description only for each state |
| kws/esp32s3 | `two-instrument-unrecorded`=1, `single-instrument-unrecorded`=2 | description only for each state |
| ic/f401re | `two-instrument-unrecorded`=3 | at least three in one state |
| ic/nano33 | `two-instrument-unrecorded`=1, `single-instrument-unrecorded`=2 | description only for each state |
| ic/esp32s3 | `two-instrument-unrecorded`=1, `single-instrument-unrecorded`=2 | description only for each state |
| ad/f401re | `documented-full-board`=3 | at least three in one state |
| ad/nano33 | `two-instrument-unrecorded`=1, `single-instrument-unrecorded`=2 | description only for each state |
| ad/esp32s3 | `two-instrument-unrecorded`=1, `single-instrument-unrecorded`=2 | description only for each state |

Across the 27 selected sessions the boundary counts are `documented-full-board`=6, `two-instrument-unrecorded`=9, `single-instrument-unrecorded`=12.

Only matching boundary states can be compared. Because no pair of task cells has at least three sessions sharing the same boundary state, the estimates file contains no ratio rows. This is a design limitation, not evidence that board effects are absent.

## Descriptive published medians

These medians are shown to answer the Report No. 1 question directly. They combine the three published sessions in each cell exactly as Report No. 1 did; the boundary analysis above explains why they are not sufficient for the stronger cross-board claim.

| Task | F401RE latency (ms) | Nano 33 latency (ms) | ESP32-S3 latency (ms) | F401RE energy (Wh/1000) | Nano 33 energy (Wh/1000) | ESP32-S3 energy (Wh/1000) |
|---|---:|---:|---:|---:|---:|---:|
| KWS | 158.926 | 224.222 | 106.4955 | 0.0213817329 | 0.00266470295 | 0.0135726302 |
| IC | 755.418 | 1232.6125 | 551.062 | 0.0718018441 | 0.0141851679 | 0.0685781363 |
| AD | 8.136 | 12.421 | 11.723 | 0.00129544679 | 0.000188938613 | 0.00143871553 |

## What a session comprises

For each selected run, the session value is the median of measured `results.duration_ms` rows after the recorded warm-up count, using the repository exporter's deterministic IQR policy. The table shows raw measured rows and retained rows. The energy value is trapezoidal integration of retained INA219 power telemetry, normalized to 1,000 retained results. Per-inference energy attribution is not used. All selected sessions record zero warm-up rows in this database; the script still applies the stored warm-up count rather than assuming zero.

The run records retain timestamps, result counts, corpus/protocol status, software version, runtime name/version, model hash, quantization, telemetry completeness, and selected boundary metadata. Ambient temperature and humidity ranges are taken from BME280 samples. They do not record a sitting identifier, cooldown/reset boundary between sessions, host version, compiler/toolchain version, or a complete per-session power-configuration record for the non-F401RE boards. Those fields remain unrecorded rather than being inferred.

The run `extra` fields carry protocol, model lineage, session labels where assigned, rerun reasons where assigned, and boundary state where documented. No separate field identifies whether adjacent sessions belong to the same sitting, so timestamps are the available evidence for temporal spacing.

## Limits of the finding

The published subset is not a random sample. It supports reporting the recorded session values and the descriptive cell medians. It does not support a boundary-matched interval comparison across boards in this dataset, and it does not justify extending the Nano 33 energy ordering into a general claim across all measured tasks.
