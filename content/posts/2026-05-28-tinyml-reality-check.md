---
title: "TinyML Reality Check: The Floor of the Curve"
slug: tinyml-reality-check
pillar: 3
format: signal_report
published_at: 2026-06-15
read_time: 14
excerpt: "Three microcontrollers, three workloads, and the MCU floor measured with board-level energy, latency variance, and telemetry provenance exposed."
editorial_summary: "Post 1 closes the Tier 1 MCU floor: all nine F401RE, Nano 33, and ESP32-S3 workload cells have three non-partial A03 runs, with energy-quarantined diagnostics kept out of headline Wh/1000."
og_image: /assets/blog/tinyml-reality-check-og.png
tags: [tinyml, edge-ai, benchmarking, mcu, methodology, signal-bench]
is_signal_report: true
signal_report_data: signal-reports/2026-05-28-tinyml-reality-check-data.yml
signal_report_visualizations:
  - hardware_performance_curve
  - wh_comparison
  - variance_illustration
model_name: "MLPerf Tiny reference workloads (KWS, IC, AD)"
model_version: "Tier 1 MCU deployment"
syndicate_to_medium: true
syndicate_to_linkedin: true
---

**Correction — 23 September 2026.** Energy figures and their comparisons have been corrected; measurement-boundary claims have been narrowed, and a selection-layer latency p99 has been recomputed from raw results. The energy error came from a mismatched result count; the p99 change uses a documented session-level calculation. The raw measurements did not change. [Corrections record](https://github.com/narteyb/signal-bench/blob/main/docs/corrections/2026-09-23-ananse-reports.md) lists the affected figures and claims.

---

## 1. Hook

All nine Tier 1 MCU cells are closed at 3/3 published A03 runs, with status OK and telemetry_partial=false for every headline run.
The tight memory case, IC on F401RE, fits: the firmware inventory records 74,884 bytes (73.13 KiB, 1 KiB = 1024 bytes) estimated SRAM against a 98,304-byte SRAM limit, leaving 23,420 bytes (22.87 KiB) margin.

Model size is not SRAM size.

That is the first reality check this post needs to make visible. The anomaly
detection model looks like the scary one on paper because the model file is
large for a microcontroller-class target. But model bytes are not the same as
runtime RAM pressure. Weights can live in Flash. SRAM pressure comes from tensor
arena allocation, stack, heap, input buffers, and framework overhead.

Post 1 tests that distinction instead of arguing it abstractly: three TinyML
workloads, three MCU targets, one measurement protocol. The measured matrix is
the baseline for this report.

## 2. Manifesto: What Is A Signal Report

Three TinyML tasks. Three MCUs. The point is not to crown a winner before the measurements arrive. The point is to make the shape of the measurement visible. I kept running into the same gap in public TinyML reporting: the story usually stops at whether a model can run, or how many milliseconds one inference takes. That is useful, but it is not enough for anyone shipping hardware that has to survive on a battery, inside a box, in a place where power and replacement parts are not abstract. Energy measurement is rare. Variance is often undisclosed. Telemetry usually comes from one view of the system. Those omissions are not moral failures. They are methodology gaps, and methodology gaps compound into bad product decisions.

The existing ecosystem deserves credit for getting TinyML this far. Edge Impulse made the AutoML and deployment workflow practical for teams that do not want to rebuild an embedded ML pipeline from scratch. MLPerf Tiny gave the field canonical workloads, reference models, and a shared vocabulary for comparing keyword spotting, image classification, anomaly detection, and related tasks. We are standing on that work. The wedge here is not that those tools are wrong. The wedge is that a team deciding whether to put inference on a microcontroller still needs board-level energy, repeatability, and environmental context in the same frame as latency and accuracy. A benchmark can be technically correct and still incomplete for a builder who has to choose a board, a power budget, and a deployment envelope.

A Signal Report ships three things every time: hardware-grounded numbers with disclosed variance, a methodology that can be reproduced from a public repo, and a wedge of analysis the reader can act on. For Post 1, that means wall-side power from an FNB58, board-side current from INA219 where available, ambient context from BME280, and inference timing reported as distributions rather than single polished numbers. I built signal-bench to make that pipeline boring: define the tasks, run the cells, capture telemetry, export the matrix, and generate the charts without hand-massaging the result. The boring part matters because trust comes from repetition, and because repeatable work lets other builders challenge the conclusion without reverse-engineering the setup. If a cell is noisy, the report should show it. If a device is efficient but slow, the report should show that too. If two boards trade places when the metric changes from latency to watt-hours, that is not a problem to smooth over; that is the point of measuring both.

This report measures keyword spotting, image classification, and anomaly detection across F401RE, Nano 33 BLE Sense Rev2, and ESP32-S3. A microcontroller is not a small cloud server, and a TinyML benchmark that ignores power, variance, and measurement context is answering a narrower question than builders actually face. The question here is what the smallest useful systems can honestly do. I would rather publish numbers with caveats than a clean table that hides the conditions that produced it. We are publishing the methodology so you can argue with the numbers.

## 3. The Matrix: What We Tested

| Task | F401RE | Nano 33 BLE Sense Rev2 | ESP32-S3 |
| --- | ---: | ---: | ---: |
| KWS | 158.9 ms<br>0.021382 Wh/1000 | 224.2 ms<br>0.002367 Wh/1000 | 106.5 ms<br>0.013221 Wh/1000 |
| IC | 755.4 ms<br>0.071360 Wh/1000 | 1232.6 ms<br>0.013698 Wh/1000 | 551.1 ms<br>0.067631 Wh/1000 |
| AD | 8.1 ms<br>0.001295 Wh/1000 | 12.4 ms<br>0.000189 Wh/1000 | 11.7 ms<br>0.001438 Wh/1000 |

Post 1 covers the 9-cell Tier 1 matrix:

- KWS, IC, and AD.
- F401RE, Nano 33 BLE Sense Rev2, and ESP32-S3.
- The plotted data contains nine MCU cells.

KWS represents always-on audio inference. IC represents a compact vision
workload. AD represents sensor anomaly detection and reconstruction. The target
set is intentionally small: one tight Cortex-M4-class baseline, one practical
Arduino-class sensor board, and one larger connected MCU class.

The table reports each cell as p50 latency and p50 Wh/1000 from the canonical A03 session set. F401RE/IC is not absent: it is measured and closed. The caveat is narrower: the original May 25 F401RE/IC energy reading is quarantined because it predates the full-board metered-rail discipline, while its latency remains in the raw provenance. The May 25 F401RE KWS/AD low-boundary rows and the May 29 F401RE KWS/AD rows with unrecorded power topology are also quarantined from the published repeat sets after the boundary audit.

## 4. The Headline Metric

- KWS: F401RE 0.021382 Wh/1000; Nano 33 0.002367 Wh/1000; ESP32-S3 0.013221 Wh/1000.
- IC: F401RE 0.071360 Wh/1000; Nano 33 0.013698 Wh/1000; ESP32-S3 0.067631 Wh/1000.
- AD: F401RE 0.001295 Wh/1000; Nano 33 0.000189 Wh/1000; ESP32-S3 0.001438 Wh/1000.

The selected headline set contains 27 A03 runs; many historical sessions lack a recorded or recoverable power boundary. The raw DB still carries diagnostic and quarantined rows: F401RE/IC baseline energy from 2026-05-25 is excluded for a pre-discipline power boundary, F401RE KWS/AD May 25 low-boundary rows and May 29 unrecorded-topology rows are excluded from the published repeat sets, and Nano33 session-3 anomaly rows are excluded for energy only. Those rows remain visible in the matrix YAML provenance.

The headline metric is Wh/1000 inferences: how much energy the board consumed
to perform 1000 model inferences. Latency answers "how fast?" Energy answers
"at what power cost?" Wh/1000 is a derived presentation unit, not a separate
MLPerf Tiny standard: it is window-level energy divided by completed inference
count, equivalent to energy per inference, then scaled to 1000 inferences and
converted to watt-hours for readability. The literature note is archived at
`results/a06_wh1k_precedent.md`.

For Post 1, energy is computed from telemetry over the inference window and
normalized by inference count. The measurement is run-level, not per-inference:
the telemetry sample rate is slower than the inference loop on some targets, so
the honest unit is window energy divided by completed inference count.

INA219 and BME280 provide board-side and environmental context. The headline
energy metric should still be read with the power-boundary note attached. These
measurements capture MCU compute plus onboard peripherals behind the selected
power boundary; external sensor loads and radio duty-cycle budgets must be
accounted separately for a deployed product. They are devkit-level measurements,
not production-module measurements: for ESP32-S3, Espressif's datasheet current
tables put radio-off CPU-active/module-level operation in the tens to low
hundreds of milliwatts at 3.3 V, so replacing the DevKitC power tree with a
production module can plausibly move the board-level number by tens to low
hundreds of milliwatts depending on regulators, USB-UART, LEDs, and radio state.
The external-baseline note is archived at `results/a04_external_baseline.md`.

MLPerf Tiny's NUCLEO-L4R5ZI energy result uses a documented device-under-test power hookup and timestamped inference windows. A direct comparison with the selected Post 1 figures requires the exact power paths and workload conditions for both datasets; many historical Post 1 boundaries were not recorded. The contribution of any power-path difference cannot be quantified from these records.

## 5. The Data

The three charts below are the evidence block for Post 1. They should be read
together: latency first, energy second, variance third.

### 5.1 Hardware Curve

<!-- chart: hardware_curve -->
Chart config: `data/charts/hardware-curve-tier1.json`.

ESP32-S3 is fastest on KWS (106.5 ms) and IC (551.1 ms). F401RE is fastest on AD (8.1 ms). The ranking does not hold across tasks, and the full Tier 1 latency span runs from 8.1 ms to 1232.6 ms, about 151.5x.

### 5.2 Wh/1000 Comparison

<!-- chart: energy_comparison_tier1 -->
Chart config: `data/charts/wh-comparison-tier1.json`.

Nano 33 is the lowest-energy target on KWS (0.002367 Wh/1000), IC (0.013698 Wh/1000), and AD (0.000189 Wh/1000). It does not match the latency winner on any task: ESP32-S3 wins KWS and IC latency, while F401RE wins AD latency.

### 5.3 KWS Narrative

Each p99 below is the median of the selected sessions' p99 inference latencies. Within a session, p99 uses linear interpolation over device-reported results retained by the latency IQR rule; the source rows and session IDs are recorded in the [corrections record](../../docs/corrections/2026-09-23-ananse-reports.md).

F401RE: 158.9 ms p50, 158.985 ms p99, 0.021382 Wh/1000, across 3 selected A03 runs. Historical boundary completeness is limited.

Nano 33 BLE Sense Rev2: 224.2 ms p50, 224.236 ms p99, 0.002367 Wh/1000, across 3 selected A03 runs.

ESP32-S3: 106.5 ms p50, 106.518 ms p99, 0.013221 Wh/1000, across 3 selected A03 runs.

KWS is the cleanest example of metric disagreement: ESP32-S3 is fastest at 106.5 ms, but Nano 33 is lowest energy at 0.002367 Wh/1000. The selected F401RE KWS runs span three days; their historical boundary record is incomplete.

### 5.4 IC Narrative

F401RE: 755.4 ms p50, 755.500 ms p99, 0.071360 Wh/1000, across 3 selected A03 runs.

Nano 33 BLE Sense Rev2: 1232.6 ms p50, 1233.227 ms p99, 0.013698 Wh/1000, across 3 selected A03 runs.

ESP32-S3: 551.1 ms p50, 551.080 ms p99, 0.067631 Wh/1000, across 3 selected A03 runs.

IC/F401RE is the tightest SRAM case but still fits. The inventory records 74,884 bytes (73.13 KiB, 1 KiB = 1024 bytes) estimated SRAM against the 98,304-byte F401RE SRAM limit, leaving 23,420 bytes (22.87 KiB) margin; the May 25 baseline is energy-quarantined only, not evidence that IC failed or was out of scope.

### 5.5 AD Narrative

F401RE: 8.1 ms p50, 8.181 ms p99, 0.001295 Wh/1000, across 3 selected A03 runs.

Nano 33 BLE Sense Rev2: 12.4 ms p50, 12.448 ms p99, 0.000189 Wh/1000, across 3 selected A03 runs.

ESP32-S3: 11.7 ms p50, 11.727 ms p99, 0.001438 Wh/1000, across 3 selected A03 runs.

AD is the file-size trap: the model file is large for this tier, but the runtime arena is small enough that all three MCU targets fit once weights are treated as Flash-resident data instead of SRAM-resident working memory.

### 5.6 Variance Illustration

<!-- chart: variance_illustration -->
Chart config: `data/charts/variance-illustration.json`.

KWS/Nano33 is the representative variance cell: p50 224.2 ms, observed min/max 224.094 ms to 224.252 ms, run-to-run stddev 0.053 ms (0.02%). All three published runs are telemetry_partial=false.

## 6. Reality Checks

The static budget check in `docs/model-budget-check.md` marks all nine MCU cells as FITS and identifies IC/F401RE as the closest SRAM case.
Published headline runs are telemetry_partial=false across all nine cells. Historical partial and diagnostic runs remain in the raw matrix only for provenance.

The main reality check is that model file size is not SRAM size. Model bytes can
live in Flash. SRAM pressure is the runtime footprint: tensor arena, stack,
heap, buffers, and framework state.

All three deployed models are INT8 quantized. That means weights and activation
tensors are represented with 8-bit integer values calibrated from the trained
floating-point model. Quantization can cost some accuracy versus float32, which
is why the model lineage and accuracy checks matter, but INT8 is the correct
operating mode for these MCU budgets: it reduces model storage, tensor-arena
pressure, and arithmetic cost enough for TFLM deployment on Cortex-M and
ESP32-class parts.

The ATmega328 boundary shows how sharp that SRAM constraint is. Its 2 KB SRAM
budget is 2,048 bytes. The smallest Post 1 activation budget is AD's estimated
12 KB tensor arena before stack, heap, serial buffers, or framework state, so
the arena alone is roughly 6x larger than the entire ATmega328 SRAM. KWS needs a
36 KB arena and IC needs a 56 KB arena. None of the three workloads is a
credible ATmega328 deployment without changing the model class and measurement
scope.

The second reality check is that MLPerf Tiny-style latency is necessary but not
sufficient. A board choice also depends on energy, variance, telemetry
coverage, tooling, and deployment context.

The third reality check is scope. This post starts at the MCU floor. It does not
claim to settle the Pi, NPU, Jetson, laptop, or cloud parts of the curve.

## 7. What This Means

Three patterns are worth carrying out of the Tier 1 matrix and into your own work. They are not universal laws. Three tasks across three MCUs is a starting point, not a population. But the point of this report is not to manufacture certainty; it is to replace vague intuition with measurements that can be inspected, repeated, and challenged. For the three tasks we tested, the useful takeaways are specific: check the right memory budget, optimize the right metric, and report the conditions that produced the number. The most useful surprise is that Nano 33 wins Wh/1000 on all three tasks even when it does not win latency, so the measured energy story is not the same as the speed story.

The first takeaway is the one that changes how you read a model card: model size is not SRAM size. The AD model looks like the scary one because its `.tflite` file is 276,976 bytes, but the static budget check shows all nine MCU cells fit once model bytes are treated as Flash-resident constant data. SRAM pressure comes from the tensor arena, stack, heap, and runtime state. The evidence is the T2.5 budget matrix and the Phase 5 inventory: IC/F401RE uses 74,884 bytes (73.13 KiB, 1 KiB = 1024 bytes) estimated SRAM against a 98,304-byte SRAM limit, leaving 23,420 bytes (22.87 KiB) margin. When evaluating a TinyML model for an MCU, check arena bytes before you panic over weight bytes, and read the linker report before changing models. The caveat is real: this is a static-graph TFLM finding. If your runtime copies weights into RAM, uses dynamic shapes, or keeps extra input buffers alive, redo the accounting.

The second takeaway is the one that decides product tradeoffs: latency and energy are related, but they are not the same ranking. A target can finish an inference faster and still burn more energy per 1000 inferences if idle power, peripheral load, or runtime overhead changes the shape of the run. The evidence comes from reading the hardware curve beside the Wh comparison chart, especially KWS, where ESP32-S3 is fastest at 106.5 ms while Nano 33 is lowest energy at 0.002367 Wh/1000, and IC, where the Nano 33 uses about one fifth the energy of the ESP32-S3 while being slower. When the device is battery-constrained, optimize Wh per 1000 inferences first and latency second, then verify the result under realistic deployment duty cycle. When the device is interaction-constrained, reverse the order. The caveat is scope: if two boards are close on both metrics, the cleaner engineering choice may be the board with better tooling, supply, or sensor integration.

The third takeaway is methodological: measurement conditions are part of the result. A benchmark number without sample count, variance, telemetry coverage, and ambient context is not wrong, but it is incomplete. The useful output is not "KWS took X microseconds." The useful output is "KWS on Nano 33 took 224.2 ms p50 with 0.053 ms run-to-run stddev (0.02%), under the recorded power and environmental conditions." When you publish TinyML results, report the run conditions. When you read them, look for those fields before comparing devices. The caveat is practical: early prototyping does not need a full telemetry rig. But once a number is used to make a board choice, a battery claim, or a customer-facing promise, the conditions belong in the report.

That is the through-line from the manifesto to the matrix. The data does not need to settle every TinyML question to be useful. It needs to make the next question sharper. For Post 1, the next question is no longer "can these models fit?" It is which combinations of task, target, and measurement condition earn their place in a real deployment. The matrix is small. The methodology is the asset.

## 8. What's Next

Further reports are planned.
