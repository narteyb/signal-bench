# A01 Full MCU Eval Status

Generated: 2026-06-30

## Status

Complete.

`src/signal_bench/eval/full_eval.py` implements the host side of the A01
streamed-sample evaluation protocol and now tolerates per-sample failures
without hanging a full run:

- loads preprocessed int8 `.npz` archives with `inputs`, `labels`, optional
  `sources`, and `metadata_json`;
- opens a USB-CDC serial connection;
- sends `EVAL <task_id> <sample_index> <base64-int8-input>`;
- expects `PRED` frames for KWS and `SCORE` frames for AD;
- computes KWS top-1 accuracy and AD clip AUROC;
- writes per-sample `predictions.csv` and persists summary rows to the SQLite
  run database;
- writes failed samples explicitly and aborts only after 20 consecutive sample
  failures;
- retries short/truncated serial frames reported as `ERR EBADLEN`.

The generated MCU firmware template in `scripts/run_p3_mcu_matrix.py` now adds
the streamed `EVAL` command alongside the existing `RUN <task_id> <iterations>`
path. The `RUN -> RESULT* -> DONE` path remains intact.

Firmware binaries were built and flashed for each board/task pair:

| Target | Task | RAM | Flash | EVAL probe |
|---|---:|---:|---:|---|
| ESP32-S3 | KWS | 69,344 / 327,680 | 430,909 / 3,342,336 | `PRED 0 107329 7` |
| ESP32-S3 | AD | 44,908 / 327,680 | 503,737 / 3,342,336 | `SCORE 0 11786 12.442124` |
| Nano 33 BLE Sense Rev2 | KWS | 94,152 / 262,144 | 210,288 / 983,040 | `PRED` for sample 2, class 6, about 224 ms |
| Nano 33 BLE Sense Rev2 | AD | 69,720 / 262,144 | 282,840 / 983,040 | `SCORE 1 12xxx 11.660621` |
| NUCLEO-F401RE | KWS | 51,612 / 98,304 | 135,836 / 524,288 | `PRED 0 158892 7` |
| NUCLEO-F401RE | AD | 27,180 / 98,304 | 209,928 / 524,288 | `SCORE 0 8084 12.442127` |

## Prepared Inputs

The full-eval host input archives required by `signal-bench eval` were generated
successfully:

- `data/eval/kws/mlperftiny-kws-test.npz`
- `data/eval/kws/mlperftiny-kws-test.metadata.json`
- `data/eval/ad/mlperftiny-ad-test.npz`
- `data/eval/ad/mlperftiny-ad-test.metadata.json`

KWS contains 4,890 full MLPerf Tiny reference-preprocessed samples. AD contains
31,360 frame-level samples with clip source IDs for clip-level AUROC
aggregation.

## Full-Eval Results

Final artifact rows are the clean, zero-failed-sample runs. Earlier Nano
diagnostic runs with serial truncation were superseded by the final rows below.

| Target | KWS top-1 | KWS run | KWS failed/retried | AD AUROC | AD run | AD failed/retried |
|---|---:|---|---:|---:|---|---:|
| ESP32-S3 | 0.8832310838445808 | `019f1b19-4353-7943-9502-72e16d1e74eb` | 0 / 0 | 0.8496875 | `019f1b27-5278-71d3-a810-a67924e18b9d` | 0 / 0 |
| Nano 33 BLE Sense Rev2 | 0.8832310838445808 | `019f1c3e-bede-7e12-8383-c35fe1f5aa8f` | 0 / 0 | 0.8496875 | `019f1bfb-8dbb-74c3-9beb-60e625e42deb` | 0 / 2 |
| NUCLEO-F401RE | 0.8832310838445808 | `019f1b03-be72-74b2-8498-bacb755ae407` | 0 / 0 | 0.8496875 | `019f1ad5-ac11-7d73-bee5-7d49296328b0` | 0 / 0 |

Per-sample artifacts:

- `data/full-eval/a01/019f1b19-4353-7943-9502-72e16d1e74eb/predictions.csv`
- `data/full-eval/a01/019f1b27-5278-71d3-a810-a67924e18b9d/predictions.csv`
- `data/full-eval/a01/019f1c3e-bede-7e12-8383-c35fe1f5aa8f/predictions.csv`
- `data/full-eval/a01/019f1bfb-8dbb-74c3-9beb-60e625e42deb/predictions.csv`
- `data/full-eval/a01/019f1b03-be72-74b2-8498-bacb755ae407/predictions.csv`
- `data/full-eval/a01/019f1ad5-ac11-7d73-bee5-7d49296328b0/predictions.csv`

The summary values are also recorded in `data/matrices/post-1-data.yml` under
`full_eval_accuracy` and in `data/p3_mcu_matrix.db`.

## Notes

The generated NUCLEO-F401RE firmware now uses the STLink VCP `Serial` path for
these builds rather than the alternate PA9/PA10 USART flag, matching the board
connection used for the live flash/probe session.
