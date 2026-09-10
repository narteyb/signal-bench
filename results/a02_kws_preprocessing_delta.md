# A02 KWS Preprocessing Delta

Generated: 2026-06-30

## Status

Complete: no material preprocessing delta found.

A02 is conditional on A01: the preprocessing delta should be characterized only
if full KWS on-device top-1 accuracy shows a material gap of at least 5
percentage points from the Python reference path.

The A01 full-eval host inputs are:

- `data/eval/kws/mlperftiny-kws-test.npz`
- `data/eval/kws/mlperftiny-kws-test.metadata.json`

The KWS variant Python reference report is
`<local-path>`.
It records:

- canonical Python reference top-1: 0.8754601226993866
- variant/TFLite reference top-1: 0.881799591002045

The streamed on-device KWS full-eval results are:

| Target | Run ID | On-device top-1 | Delta vs variant reference |
|---|---|---:|---:|
| ESP32-S3 | `019f1b19-4353-7943-9502-72e16d1e74eb` | 0.8832310838445808 | +0.14314928425357934 pp |
| Nano 33 BLE Sense Rev2 | `019f1c3e-bede-7e12-8383-c35fe1f5aa8f` | 0.8832310838445808 | +0.14314928425357934 pp |
| NUCLEO-F401RE | `019f1b03-be72-74b2-8498-bacb755ae407` | 0.8832310838445808 | +0.14314928425357934 pp |

The largest observed gap from the variant Python reference is about 0.14
percentage points, far below the 5 percentage-point threshold. No MFCC/input
preprocessing delta characterization is warranted for Post 1.
