# Phase 1 Measurement Protocol

Date: 2026-06-11

This document is the Phase 1 source of truth for publication-grade SLM/VLM
measurements. Earlier `warm_steady_state_v1` artifacts are retained only as
reference data. They are not canonical publication results.

## Canonical Protocol: `n20_plus_5_v1`

Every benchmark session uses 5 warmup invocations followed by at least 20 valid
measured invocations.

1. Start from the target in a known reachable state.
2. Record target identity, OS version, kernel, runtime version, model name,
   model source, model digest, quantization format, context length, and exact
   command used to run the benchmark.
3. Start the three-vector telemetry capture before the first warmup invocation.
4. Run 5 warmup invocations. Warmups use the same task suite and runtime path
   as measured invocations, are stored with `is_warmup=true`, and are excluded
   from all publication statistics.
5. Run measurement invocations until 20 valid measured invocations are available.
   Runs excluded by the thermal gate remain in the raw report but do not count
   toward the 20 valid measured invocations.
6. Stop telemetry after the final invocation and emit the canonical report.

## Statistical Requirements

Publication reports must include P50, P95, P99, and sample standard deviation
for every scalar metric. Single-shot results, 5-run results, and reports without
tail statistics are not publication-grade.

Required scalar metrics include:

- tokens/second
- time-to-first-token in milliseconds
- FNB58 Wh per 1000 output tokens
- FNB58 joules per output token
- INA219 joules per output token
- dual-meter cross-check relative delta
- CPU temperature at run start and run end
- platform thermal gate values at run start and run end

The p99/p50 stability gate is reported for each metric where the ratio is
meaningful. The default threshold is `1.4`.

## Thermal And Throttle Control

For Raspberry Pi 5 runs:

- Record `vcgencmd measure_temp` at the start and end of every individual run,
  including warmups.
- Record `vcgencmd get_throttled` at the start of every individual run.
- Abort an individual run before generation if any lower active throttle bit
  0-3 is non-zero.
- For long-running generation tasks, poll temperature and throttle state during
  generation. Abort immediately if the target crosses the 70 C Pi limit or any
  active lower throttle bit appears before the task completes.
- Flag and exclude any measured run whose start or end CPU temperature exceeds
  70 C.
- Record historical upper throttle bits 16-19. Historical bits are context; by
  themselves they do not invalidate a run whose active lower bits are clear.
- Pi 5 + Hailo sessions must bypass the INA219 rail-side shunt. The Adafruit
  INA219 breakout's default 0.1 ohm shunt caused active Pi undervoltage under
  combined Pi 5 + Hailo-10H load in Entry 17: `vcgencmd get_throttled` flipped
  to `throttled=0x50005`, while the INA219 rail-side voltage dropped to about
  4.96 V. For any Pi 5 + Hailo session, route the FNB58 output directly to the
  Pi 5 USB-C input and publish the run as FNB58 wall-side partial telemetry
  with BME280 ambient context. The INA219 remains valid for Pi 5 CPU-only
  sessions, where the current draw is lower and did not trigger undervoltage.
  This constraint is specific to the combined Pi 5 + Hailo power path.

Platform equivalents must be used on other targets, for example `tegrastats` on
Jetson.

For macOS / Apple Silicon runs:

- Die temperatures in Celsius are not available through public APIs on the M1
  Max host used for Phase 1.
- The thermal indicator is `powermetrics --samplers thermal`, reported as the
  hardware thermal management system's pressure level:
  `0=nominal`, `1=moderate`, `2=heavy`, `3=trapping`.
- Record numeric thermal pressure at the start and end of every individual run,
  including warmups.
- Abort or exclude any run whose end pressure is `>=2` (`heavy` or worse).
  Pressure levels `0` and `1` are permitted and must be reported.
- The pressure trajectory across the measured runs is the Apple Silicon thermal
  drift indicator.
- Before any benchmark run, preflight must confirm AC power is active, Low Power
  Mode is off, and the battery is either at 100% or actively charging. If
  Optimized Battery Charging leaves the battery below 100% while reporting
  `not charging`, the FNB58 charger-side meter underreads actual system energy
  because the battery can silently supply the deficit. Disable Optimized Battery
  Charging and wait for the battery to reach at least 95%, or charge to 100%
  with Optimized Battery Charging enabled, before rerunning.
- This is a platform-specific adaptation for Apple Silicon only. It does not
  change the Pi 5 70 C gate or the Jetson Celsius-based gate.

## Standard LLM Task Suite

Every LLM benchmark session uses the same three task classes on every target:

1. Throughput task: a 512-token generation request, fixed seed where supported.
2. Latency task: a 64-token generation request, fixed seed where supported.
3. Classification task: a short deterministic classification request used for
   accuracy scoring.

The report records the exact prompt text, decode parameters, prompt token count,
and completion token count for every task invocation.

## Energy Metrics

The headline Phase 1 energy metric is:

```text
FNB58 Wh per 1000 output tokens
```

FNB58 is the wall-side / USB cable delivery measurement point. INA219 0x40 is
the Pi 5V system rail measurement point. Reports must retain and label both:

- FNB58: USB cable delivery, used for headline Wh/1000 tokens.
- INA219 0x40: 5V system rail draw, reported as context and cross-check.

The dual-meter cross-check compares integrated joules over the same invocation
window. A non-zero delta is expected because the meters sit at different points
in the power path, but the delta is still reported and flagged when it exceeds
the configured threshold.

## Version Pinning

Every canonical report records:

- OS version and kernel
- runtime name and version
- runtime concurrency / thread settings when the backend exposes them
- model name, source, digest, and local artifact size when available
- quantization format
- context length
- prompt token count per task invocation
- completion token count per task invocation
- decode parameters, including seed when supported
- telemetry sources and measurement points
- target cooling policy and any benchmark-specific fan configuration
- git commit hash and dirty/clean worktree state

## Reproducibility Footer

Every canonical report includes the exact command used to rerun the measurement
on equivalent hardware, including host, user, model, run counts, and output
location.
