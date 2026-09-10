# Post 1 Pre-Publication Review

Date: 2026-07-01

Update 2026-07-06: F401RE KWS/AD boundary quarantine and rerun supersedes the
F401RE AD spread finding in this review. See
`results/f401re_kws_ad_boundary_rerun.md`.

Update 2026-07-08: F401RE KWS/AD fresh documented-boundary rerun supersedes the
July 6 interim KWS/AD values. The active F401RE KWS/AD basis is now three
documented-boundary sessions per cell spanning July 6, July 7, and July 8. See
`results/f401re_kws_ad_fresh_sessions.md`.

Draft reviewed: `content/posts/2026-05-28-tinyml-reality-check.md`

Data sources reviewed:

- `content/signal-reports/2026-05-28-tinyml-reality-check-data.yml`
- `data/matrices/post-1-data.yml`
- `data/charts/hardware-curve-tier1.json`
- `data/charts/wh-comparison-tier1.json`
- `data/full-eval/a01/*/predictions.csv`
- `docs/model-budget-check.md`
- `models/reference/manifest.yaml`
- `results/a01_full_mcu_eval_status.md`
- `results/a04_external_baseline.md`
- `results/a06_wh1k_precedent.md`
- `/tmp/tiny_results_v1.0/closed/STMicroelectronics/results/NUCLEO_L4R5ZI/`
- `/tmp/tiny_results_v1.0/closed/OctoML/results/microtvm_cmsis_nn/NUCLEO_L4R5ZI/`

Feynman status: `feynman audit content/posts/2026-05-28-tinyml-reality-check.md`
was attempted. The CLI installed its dependencies, entered the TUI, then crashed
with `Rendered line 35 exceeds terminal width (83 > 80)` before producing an
audit result. Citation and near-neighbor checks below were therefore completed
manually.

## Check 1: Claims-to-Data Traceability

| Draft claim | Source artifact | Status |
|---|---|---|
| 9 Tier 1 MCU cells are closed at 3/3 published A03 runs; headline runs are `telemetry_partial=false`. | `content/signal-reports/2026-05-28-tinyml-reality-check-data.yml` -> `matrix.published_cells`: 9 cells, each `published_run_count: 3`; each listed run has `telemetry_partial: false`. | PASS |
| F401RE/IC tight memory case: 74,884 bytes (73.13 KiB, 1 KiB = 1024 bytes) estimated SRAM against a 98,304-byte SRAM limit, leaving 23,420 bytes (22.87 KiB) margin. | `docs/model-budget-check.md` and `models/reference/manifest.yaml` report IC/F401RE estimated SRAM as 74,884 bytes against 98,304 bytes, leaving 23,420 bytes. | PASS - RESOLVED |
| Matrix table latency and Wh/1000 values for all 9 cells. | `content/signal-reports/2026-05-28-tinyml-reality-check-data.yml` -> `matrix.published_cells[].summary`; `data/charts/hardware-curve-tier1.json`; `data/charts/wh-comparison-tier1.json`. | PASS |
| KWS Wh/1000 headline: F401RE 0.021382; Nano 33 0.002631; ESP32-S3 0.013573. | Current regenerated matrix/chart values after the F401RE fresh documented-boundary rerun. | PASS - UPDATED 2026-07-08 |
| IC Wh/1000 headline: F401RE 0.071802; Nano 33 0.014185; ESP32-S3 0.068578. | `matrix.published_cells`: IC p50 energy values 0.071801844, 0.014185168, 0.068578136. | PASS |
| AD Wh/1000 headline: F401RE 0.001295; Nano 33 0.000189; ESP32-S3 0.001435. | Current regenerated matrix/chart values after the F401RE fresh documented-boundary rerun. | PASS - UPDATED 2026-07-08 |
| Published headline set uses 27 boundary-consistent A03 runs. | 9 published cells x 3 run IDs each; F401RE KWS/AD May 25 low-boundary rows and May 29 unrecorded-topology rows are excluded from the published repeat sets. | PASS - UPDATED 2026-07-08 |
| F401RE/IC May 25 baseline is energy-quarantined but latency-valid; Nano33 session-3 anomaly rows are energy-excluded. | `content/signal-reports/...data.yml` -> `matrix.energy_quarantines`; `data/matrices/post-1-data.yml` quarantine warnings. | PASS |
| Wh/1000 is derived from energy per inference rather than an MLPerf Tiny standard. | `results/a06_wh1k_precedent.md`; MLPerf Tiny result files report `uJ/inf`, not `Wh/1000`. | PASS |
| ESP32-S3 production-module delta can plausibly be tens to low hundreds of milliwatts. | Espressif ESP32-S3 datasheet active-mode current tables: modem-sleep CPU cases ~13.2-107.9 mA at 3.3 V and RF active peaks 88-340 mA. | PASS |
| ESP32-S3 is fastest on KWS and IC; F401RE fastest on AD; full Tier 1 latency span 8.136 ms to 1232.612 ms, about 151.5x. | `matrix.published_cells[].summary.latency_ms.p50`; 1232.6125 / 8.136 = 151.5. | PASS - UPDATED 2026-07-08 |
| Nano 33 is lowest-energy target on KWS, IC, and AD. | `matrix.published_cells[].summary.energy_wh_per_1000.p50`. | PASS |
| KWS narrative p50, p99, Wh/1000, variance, and 3/3 OK rows. | KWS rows in `matrix.published_cells`; run IDs: F401RE `019f366f...`, `019f3d8a...`, `019f43e6...`; Nano33 `019e5da7...`, `019e674c...`, `019e756b...`; ESP32-S3 `019e5d8a...`, `019e653b...`, `019e71e7...`. | PASS - UPDATED 2026-07-08 |
| IC narrative p50, p99, Wh/1000, variance, and 3/3 OK rows. | IC rows in `matrix.published_cells`; run IDs: F401RE `019e7598...`, `019e759a...`, `019e75fe...`; Nano33 `019e5daa...`, `019e674a...`, `019e7569...`; ESP32-S3 `019e5d8c...`, `019e653a...`, `019e71e6...`. | PASS |
| AD narrative p50, p99, Wh/1000, variance, and 3/3 OK rows. | AD rows in `matrix.published_cells`; run IDs: F401RE `019f3676...`, `019f3d8d...`, `019f43ea...`; Nano33 `019e5dac...`, `019e6748...`, `019e7567...`; ESP32-S3 `019e5d8e...`, `019e6538...`, `019e71e4...`. | PASS - UPDATED 2026-07-08 |
| F401RE AD carries the largest Wh/1000 spread in the published set. | Superseded. The July 8 F401RE KWS/AD fresh documented-boundary rerun showed the old roughly 72.6% AD variance was a mixed-boundary artifact. Current documented-boundary AD energy CV is 1.03%; KWS energy CV is 0.99%. | SUPERSEDED - UPDATED 2026-07-08 |
| KWS/Nano33 variance illustration: p50 224.222 ms, observed min/max 224.094-224.252 ms, stddev 0.053 ms (0.02%), all three published runs non-partial. | `variance_illustration.series[0].runs`, `variance_illustration.meta`, and KWS/Nano33 row in `matrix.published_cells`. | PASS |
| Static budget check marks all nine cells FITS and identifies IC/F401RE as closest SRAM case. | `docs/model-budget-check.md`; `models/reference/manifest.yaml`. | PASS |
| AD model file is 276,976 bytes; AD arena 12 KB; KWS arena 36 KB; IC arena 56 KB. | `models/reference/manifest.yaml`; `docs/model-budget-check.md`. | PASS |
| ATmega328: 2 KB / 2,048 bytes SRAM; AD 12 KB arena is about 6x larger; KWS 36 KB and IC 56 KB. | `docs/model-budget-check.md` for arena estimates; ATmega328 SRAM value is a public hardware spec, not otherwise in repo. | PASS WITH EXTERNAL SPEC ASSUMPTION |
| Nano 33 uses about 4.8x less Wh/1000 than ESP32-S3 on IC. | 0.068578136 / 0.014185168 = 4.835. | PASS |
| "Three tasks across three MCUs", "next four reports", "five posts total", "bi-weekly cadence". | Editorial/scope claims in the draft, not measurement claims. They are internally consistent with section 8 but not data artifacts. | N/A |

## Check 2: Internal Consistency

Result: PASS.

Passes:

- The latency and energy values in the matrix and narrative sections trace to
  the same `matrix.published_cells` A03 run sets, with explicit energy-only
  quarantines for superseded/diagnostic rows.
- The post does not use the superseded F401RE/IC May 25 energy value in headline
  Wh/1000.
- The KWS and AD accuracy metadata in the chart data traces to A01 full-eval
  results in `data/matrices/post-1-data.yml`, with matching `predictions.csv`
  row counts:
  - KWS: 4,890 rows per target, value 0.8832310838445808.
  - AD: 31,360 rows per target, value 0.8496875.

Resolved flags:

- The F401RE/IC memory claim now matches the static budget artifact:
  74,884 bytes estimated SRAM / 23,420 bytes margin.
- Superseded 2026-07-08: the F401RE AD spread sentence must no longer identify
  F401RE AD as the largest spread based on the May 25 low-boundary row. The
  fresh documented-boundary AD energy CV is 1.03%; F401RE KWS energy CV is 0.99%.

## Check 3: Citation Accuracy

Feynman: attempted, but no usable output due to the TUI crash described above.

Manual citation/source status:

| Source / cited claim | Verification | Status |
|---|---|---|
| MLPerf Tiny provides canonical workloads/reference models/shared vocabulary for KWS, IC, AD. | MLCommons describes MLPerf Tiny as measuring trained-model inference on Tiny systems, lists benchmark datasets/quality targets, and names KWS, IC, and AD among the suite tasks. Sources: <https://mlcommons.org/benchmarks/inference-tiny/> and <https://mlcommons.org/2021/06/mlperf-tiny-inference-benchmark/>. | PASS |
| MLPerf Tiny energy reporting uses energy per inference, not Wh/1000. | MLCommons tiny result files report `Energy/Inf.` and `uJ/inf`; `results/a06_wh1k_precedent.md` correctly frames Wh/1000 as a derived presentation unit. | PASS |
| TinyML Summit precedent for per-1000-inference energy framing. | TinyML Summit 2021 materials include "miliJoules for 1000 Inferences: Machine Learning Systems on Chip 'on the Cheap'." Source: <https://cms.tinyml.org/wp-content/uploads/summit2021/tinyMLSummit2021d3_Keynote_MARCULESCU.pdf>. | PASS |
| Edge Impulse made practical deployment workflow available for Nano 33-class teams. | Edge Impulse's Nano 33 BLE Sense docs state the board is fully supported, can sample data, build models, and deploy trained ML models from the studio. Source: <https://docs.edgeimpulse.com/hardware/boards/arduino-nano-33-ble-sense>. | PASS |
| Espressif current tables support the production-module power-boundary caveat. | ESP32-S3 datasheet active-mode and modem-sleep current tables support the draft's "tens to low hundreds of milliwatts" framing at 3.3 V. Source: <https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf>. | PASS |
| TFLM SRAM-vs-Flash framing: model bytes are not the same as tensor arena/runtime RAM. | Repo source `docs/model-budget-check.md` and `models/reference/manifest.yaml` support the local claim. External TFLM memory-management references also support tensor-arena accounting as the relevant runtime RAM concept. | PASS |

No citation was found where the paper/source directly contradicted the claim as
written. The two blockers are data-claim consistency issues, not external-source
misrepresentations.

## Check 4: Near-Neighbor Sanity Check

Feynman `/replicate`: not used because the available Feynman TUI crashed during
the required audit attempt. Manual raw-result inspection was used instead.

Near-neighbor source: MLCommons `tiny_results_v1.0`, NUCLEO-L4R5ZI. This is not
the same MCU as NUCLEO-F401RE, but it is a useful Cortex-M-class sanity check.

| Cell | Local F401RE | MLPerf Tiny v1.0 NUCLEO-L4R5ZI near-neighbor | Ratio / assessment |
|---|---:|---:|---|
| KWS performance | 158.926 ms p50 = 6.29 inf/s | STMicroelectronics KWS median throughput 13.323 inf/s | L4R5ZI is ~2.1x faster; plausible given different MCU and optimized submission stack. |
| KWS energy | 0.021381733 Wh/1000 = 76,974.2 uJ/inf | STMicroelectronics KWS median energy 3,371.738 uJ/inf | Local is ~22.8x higher; PASS WITH CAVEAT because the post now states the MLPerf Tiny DUT energy-window boundary is not directly comparable to the Post 1 devkit-level rail boundary. |
| KWS accuracy | Local A01 top-1 0.883231 | STMicroelectronics KWS top-1 90.2%; OctoML CMSIS-NN KWS top-1 90.1% | Difference ~1.9 percentage points; within sanity threshold. |
| AD performance | 8.136 ms p50 = 122.91 inf/s | STMicroelectronics AD median throughput 131.950 inf/s; OctoML CMSIS-NN AD 116.212 inf/s | Local is in-family. |
| AD energy | 0.001295447 Wh/1000 = 4,663.6 uJ/inf | STMicroelectronics AD median energy 322.977 uJ/inf; OctoML CMSIS-NN AD 443.184 uJ/inf | Local is ~10.5x to ~14.4x higher; PASS WITH CAVEAT because the post now states the MLPerf Tiny DUT energy-window boundary is not directly comparable to the Post 1 devkit-level rail boundary. |
| AD accuracy | Local A01 AUROC 0.8496875 | STMicroelectronics AD AUC 0.86; OctoML CMSIS-NN AD AUC 0.86 | Difference ~0.01 AUROC; in-family. |

Local energy conversion:

- Wh/1000 to uJ/inf: `Wh/1000 * 3600 J/Wh * 1e6 uJ/J / 1000`.
- KWS F401RE: `0.021381733 Wh/1000 -> 76,974.2 uJ/inf`.
- AD F401RE: `0.001295447 Wh/1000 -> 4,663.6 uJ/inf`.

Interpretation: accuracy and latency are sane relative to the L4R5ZI
near-neighbor. Energy diverges by more than the brief's 10x threshold, and the
post now carries the Tech Lead-signed-off caveat that MLPerf Tiny uses
EnergyRunner/ULPMark timestamped inference windows on the isolated DUT energy
path, while Post 1 uses devkit-level rail measurement including USB controller,
voltage regulator, and other devkit overhead.

## Overall Verdict

PASS.

The three Tech Lead-requested corrections were made in this commit and signed
off as the resolution path:

1. F401RE/IC memory numbers now match the artifact-backed `74,884 bytes /
   23,420 bytes` values.
2. Superseded 2026-07-08: the largest Wh/1000 spread statement was rewritten
   after the F401RE KWS/AD fresh documented-boundary rerun; F401RE AD is no
   longer supported as the spread example.
3. The post now includes the required MLPerf Tiny DUT energy-window versus
   Post 1 devkit-level rail measurement caveat.

Hardware reruns were performed on July 6, July 7, and July 8 to replace F401RE
KWS/AD rows whose power topology was either low-boundary or unrecorded.
