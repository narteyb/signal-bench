# Post 1 TinyML Task Selection

## Executive Summary

Post 1 will benchmark three MLPerf Tiny tasks: keyword spotting (KWS), image
classification (IC), and anomaly detection (AD). The decision is scoped to Post
1 only; additional task variants remain outside this release. The baseline matrix remains fixed
inputs across targets; live-input variants are noted as Phase 5 options, not as
requirements for the first report.

## Version Pin

The task set is pinned to the current MLPerf Tiny public benchmark definitions
reported by MLCommons for v1.3. The public MLCommons Tiny page lists KWS, IC,
VWW/person detection, AD, and streaming wakeword as available in v1.3, while the
public `mlcommons/tiny` repository still exposes older release tags. T2.2 will
pin exact model files and source commits; T2.1 locks the benchmark tasks and
their intended role in Post 1.

## Task Decisions

### KWS: Keyword Spotting

KWS uses the Speech Commands dataset with a DS-CNN reference model and a 90%
top-1 quality target. It is the audio task in the matrix and is the most
natural MCU TinyML story: small inputs, compact model family, and a direct
mapping to wake-word or command recognition devices. The F401RE memory risk is
low relative to the other tasks; published Tiny work commonly treats the small
DS-CNN KWS model as comfortably under the 96KB RAM pressure point once TFLM
arena sizing is handled. A live variant is plausible on the Nano 33 BLE Sense
Rev2 using its built-in PDM microphone, but the Post 1 baseline remains
fixed-input KWS for target-to-target comparability.

### IC: Image Classification

IC uses CIFAR-10 with a ResNet-family reference model and an 85% top-1 quality
target. It supplies the vision workload without requiring a detection pipeline,
camera driver, or post-processing stack in the baseline. The memory budget is
tightest here among the selected always-run tasks: the historical Tiny IC
ResNet8 model is roughly at the edge of the F401RE flash/RAM comfort zone, so
T2.7 must verify the selected IC variant before Phase 5. A live camera variant
is plausible on the Pi 5 with Camera Module 3, but it is editorial enrichment,
not part of the matrix contract.

### AD: Anomaly Detection

AD uses ToyADMOS machine-sound data with a dense autoencoder reference model and
a 0.85 AUC quality target. It adds the sensor-time-series and industrial
monitoring angle that KWS and IC do not cover. AD is also the highest budget
risk: the historical Tiny autoencoder artifact is substantially larger than
KWS and can exceed what the F401RE can host without careful variant selection,
quantization, and arena control. That risk is acceptable for Post 1 because a
"too large to fit" result on the smallest target is itself meaningful, but T2.7
must make the final call before Phase 5 execution. A live variant may use the
Nano 33 IMU or the MPU-6050, but the baseline uses fixed reference inputs.

## Why VWW Is Cut

MLPerf Tiny's VWW/person-detection task is valid and useful, but it is the
right task to drop for Post 1. It adds another vision-classification workload,
not another modality. Running four tasks would add about 25% to Phase 5's
matrix, telemetry, analysis, and reporting work while adding less narrative
breadth than AD. KWS plus IC plus AD demonstrates that signal-bench can compare
audio, image, and sensor-style inference across MCUs, SBCs, local desktop, and
cloud reference targets. That is the stronger first-report claim.

The new MLPerf Tiny v1.3 streaming wakeword benchmark is also out of scope for
Post 1. It is important future work, but it changes the measurement shape from
single-inference latency and energy into continuous-stream behavior. Post 1
needs a small, reproducible matrix before adding streaming semantics.

## Out of Scope

This document does not select exact model files, hashes, conversion tool
versions, TFLM arena sizes, ONNX export paths, or live-input target assignments.
T2.2 pins model provenance and hashes. T2.3 through T2.6 perform conversions.
T2.5 verifies memory budgets. T2.6 defines the Python orchestration scaffold
consumed by Phase 5. The sourced Post 1 reference bytes and MCU target-fit
decisions are indexed in `models/reference/manifest.yaml`; the detailed budget
analysis lives in `docs/model-budget-check.md`.

## References

- MLCommons MLPerf Inference: Tiny benchmark summary:
  https://mlcommons.org/benchmarks/inference-tiny/
- MLCommons Tiny working group:
  https://mlcommons.org/working-groups/benchmarks/tiny/
- MLCommons Tiny repository:
  https://github.com/mlcommons/tiny
- MLPerf Tiny benchmark paper:
  https://arxiv.org/abs/2106.07597
