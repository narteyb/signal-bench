# A04 External Baseline Comparison

Generated: 2026-06-30

## Sources Checked

- MLCommons MLPerf Inference: Tiny benchmark page:
  <https://mlcommons.org/benchmarks/inference-tiny/>
- MLCommons `tiny_results_v1.0` repository:
  <https://github.com/mlcommons/tiny_results_v1.0>
- MLCommons `tiny_results_v0.7` repository:
  <https://github.com/mlcommons/tiny_results_v0.7>
- Edge Impulse public documentation and forum search results for Arduino Nano
  33 BLE Sense, ESP32, keyword spotting, image classification, and anomaly
  timing examples.

## Exact Overlap

No exact public baseline cell was found for the Post 1 target set:

- ESP32-S3 DevKitC + MLPerf Tiny KWS/AD/IC
- Arduino Nano 33 BLE Sense Rev2 + MLPerf Tiny KWS/AD/IC
- NUCLEO-F401RE + MLPerf Tiny KWS/AD/IC

The MLPerf Tiny v0.7 and v1.0 repositories contain nearby STM32 NUCLEO-L4R5ZI
results, but that board uses a different STM32L4R5 MCU: Cortex-M4 at 120 MHz,
640 KB SRAM, and 2 MB Flash. It is therefore a contextual baseline, not an
overlapping cell for the F401RE, Nano 33, or ESP32-S3 rows.

## Contextual MLPerf Tiny Near-Neighbor

MLPerf Tiny v1.0 includes NUCLEO-L4R5ZI rows from STMicroelectronics and OctoML.
Examples:

| Source | Board | Task | Metric | Value | Local path inspected |
|---|---|---:|---|---:|---|
| STMicroelectronics v1.0 | NUCLEO-L4R5ZI | KWS | median throughput | 13.323 inf/s | `/tmp/tiny_results_v1.0/closed/STMicroelectronics/results/NUCLEO_L4R5ZI/kws/performance/results.txt` |
| STMicroelectronics v1.0 | NUCLEO-L4R5ZI | KWS | median energy | 3371.738 uJ/inf | `/tmp/tiny_results_v1.0/closed/STMicroelectronics/results/NUCLEO_L4R5ZI/kws/energy/results.txt` |
| STMicroelectronics v1.0 | NUCLEO-L4R5ZI | AD | median throughput | 131.950 inf/s | `/tmp/tiny_results_v1.0/closed/STMicroelectronics/results/NUCLEO_L4R5ZI/ad/performance/results.txt` |
| STMicroelectronics v1.0 | NUCLEO-L4R5ZI | AD | median energy | 322.977 uJ/inf | `/tmp/tiny_results_v1.0/closed/STMicroelectronics/results/NUCLEO_L4R5ZI/ad/energy/results.txt` |
| OctoML v1.0 CMSIS-NN | NUCLEO-L4R5ZI | KWS | median throughput | 10.019 inf/s | `/tmp/tiny_results_v1.0/closed/OctoML/results/microtvm_cmsis_nn/NUCLEO_L4R5ZI/kws/performance/results.txt` |
| OctoML v1.0 CMSIS-NN | NUCLEO-L4R5ZI | AD | median throughput | 116.212 inf/s | `/tmp/tiny_results_v1.0/closed/OctoML/results/microtvm_cmsis_nn/NUCLEO_L4R5ZI/ad/performance/results.txt` |

Post 1's F401RE KWS p50 latency is 158.925 ms, equivalent to about 6.29
inferences/s. The L4R5ZI near-neighbor is faster, which is expected because it
uses a different MCU with a higher 120 MHz clock, more SRAM/Flash, and a
submission-optimized MLPerf stack. Post 1's F401RE AD p50 latency is 8.138 ms,
equivalent to about 122.88 inferences/s, which is in the same broad range as the
L4R5ZI AD rows.

Because the hardware and software stacks are not identical, these are sanity
checks only. They should not be represented as direct leaderboard wins or
losses.

## Edge Impulse

No Edge Impulse public benchmark table was found for the exact Post 1 cells.
Edge Impulse documentation confirms Arduino Nano 33 BLE Sense support and forum
threads include project-specific timing examples, but those examples use custom
datasets, generated impulses, and Edge Impulse SDK pipelines rather than the
MLPerf Tiny reference models and datasets used in Post 1.

## Recommended Post Framing

Post 1 should say that no exact public baseline was found for the tested
board/task cells. MLPerf Tiny provides task-compatible and MCU-class
near-neighbor context, especially STM32 NUCLEO-L4R5ZI, but the comparison is not
cell-equivalent. Edge Impulse confirms ecosystem relevance for Nano 33 BLE Sense
and ESP32-class deployment, but no exact MLPerf Tiny-equivalent Edge Impulse
baseline was found.
