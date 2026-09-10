# P4 Brief 2 - Hailo-10H X-Corpus DFC Compile

## Summary
1. Result: PASS. DFC 5.3.0 ran in the dedicated Modal app `hailo-dfc-compile` on A10G, separate from measurement.
2. Compile: IC, KWS, and AD all compiled to `hw_arch=hailo10h`; HEFs were kept out-of-tree in `<local-path>`.
3. Measurement: Pi 5 + Hailo-10H ran all three X-corpus HEFs with HailoRT 5.1.1, kernel `6.18.29+rpt-rpi-2712`, PCIe Gen3 `Speed 8GT/s, Width x1`; timer-boundary parity rerun wraps input/output buffer binding plus `configured.run()`.
4. Curve-real Wh/1000: IC `0.001359`, KWS `0.001299`, AD `0.002447` using FNB58 window energy.
5. Accuracy proxies: IC top1 `0.8700` vs lineage `0.8577`; KWS top1 `0.8100` on the small reference-preprocessed subset vs lineage `0.8818`; AD clip AUROC `0.8333` vs lineage `0.8391`.
6. License guardrail: no `.whl`, `.hef`, or `.har` is tracked or untracked in the repo; `.gitignore` covers these extensions.

## R1 Findings
- The live Hailo DFC guide URL was gated in the browser session, so the install path was reconciled from the DFC 5.3.0 wheel metadata and actual import/compile behavior.
- The proprietary wheel was staged to Modal Volume `hailo-dfc` as `/hailo_dataflow_compiler-5.3.0-py3-none-linux_x86_64.whl`; it was not copied into the repo.
- The working custom-model path is `hailo_sdk_client.ClientRunner`: `translate_tf_model(...)` -> `optimize(calib, data_type=CalibrationDataType.np_array)` -> `save_har(...)` -> `compile()`.
- The Modal image needed Ubuntu 22.04, Python 3.10, CUDA A10G, `clang`, Graphviz libs, LAPACK/ATLAS, `psutil`, and the DFC wheel installed from the private Volume at runtime.
- KWS required MLPerf Tiny reference preprocessing. The repo's older KWS subset extraction uses the right shape but not the variant's waveform-normalized reference path, which produced a false low proxy before correction.
- AD acceptance proxy must be clip-level, matching the variant lineage: mean reconstruction error over clip frames, then AUROC across clips.

## Compile Results
| Workload | Model input | Calibration | DFC | GPU | HEF size | HAR size | Elapsed | Target |
|---|---|---:|---|---|---:|---:|---:|---|
| IC | `ic_float.tflite` | `(100, 32, 32, 3)` | 5.3.0 | NVIDIA A10 | 237,568 B | 981,851 B | 75.98 s | `hailo10h` |
| KWS | `kws_float.tflite` | `(100, 49, 10, 1)` | 5.3.0 | NVIDIA A10 | 172,032 B | 579,096 B | 77.78 s | `hailo10h` |
| AD | `ad_float.tflite` | `(100, 640)` | 5.3.0 | NVIDIA A10 | 270,336 B | 2,212,659 B | 63.84 s | `hailo10h` |

Notes: KWS emitted a DFC normalization warning because MFCC tensors are not 0-255 normalized. Local pre-run sanity remained valid: KWS float TFLite top1 on the reference-preprocessed subset was `0.82`.

## Measurement Results
| Workload | Run ID | Status | Inferences | Mean ms | P50 ms | P99 ms | Accuracy proxy | Telemetry counts | Wh/1000 |
|---|---|---|---:|---:|---:|---:|---|---|---:|
| IC | `019e62c6-0978-7530-9b11-ce7684ac6508` | PASS | 31,818 | 0.835 | 0.838 | 0.883 | top1 `0.8700`, 10 classes | BME280 32, FNB58 128, partial `false` | 0.001359 |
| KWS | `019e62c7-2bb3-75e3-8edb-a94e7fc6800e` | PASS | 34,247 | 0.789 | 0.791 | 0.840 | top1 `0.8100`, 12 classes | BME280 33, FNB58 131, partial `false` | 0.001299 |
| AD | `019e62cb-39f4-7193-8edb-9a061e5cb118` | PASS | 50,000 | 0.770 | 0.756 | 0.812 | clip AUROC `0.8333`, 160 clips | BME280 83, FNB58 330, partial `false` | 0.002447 |

All runs passed the Brief-1 HailoAdapter preflight: `/dev/hailo0` present and `hailortcli fw-control identify` reported `Device Architecture: HAILO10H`.
The aligned rerun used USB-C power through the FNB58 and excluded INA219 from the Hailo run because the GPIO INA219 path was not in the Pi power feed and produced stale/glitchy rows.

## Metadata
- Runtime: HailoRT CLI `5.1.1`, pyHailoRT `5.1.1`, firmware `5.1.1 (release,app)`.
- Pi kernel: `6.18.29+rpt-rpi-2712`.
- PCIe: Gen3, `LnkSta: Speed 8GT/s, Width x1 (downgraded)`.
- Batch size: 1.
- Adapter I/O: `FormatType.FLOAT32` input; output `UINT8` for IC/KWS and `FLOAT32` for AD.
- HEF provenance: local X-corpus exports from `<local-path>`, compiled by DFC `5.3.0`.

## Artifacts
- Public recipe: `recipes/hailo/p4_xcorpus_hailo10h.md`.
- Local/private compile inputs: `<local-path>`.
- Local/private HEF/HAR outputs: `<local-path>`.
- Measurement DB: `data/p4_hailo_xcorpus_aligned.db`; supersedes the pre-alignment DB `data/p4_hailo_xcorpus.db` for timer-boundary comparisons.
- Scratch per-run reports: `reports/scratch/p4_hailo_xcorpus_{ic,kws,ad}_aligned.md`.
