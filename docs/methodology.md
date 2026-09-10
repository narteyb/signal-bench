# signal-bench Methodology

Draft created from Experiment 01. The M5 methodology doc will expand this into the public release version.

## Power Meter Authority

Meter authority is tier-specific. MCU rows use INA219 rail-side power as the
authoritative energy source because it samples the board rail through the
MCP2221A I2C path at the highest available MCU-tier cadence. SBC rows use the
inline FNB58 as the authoritative whole-board input meter. Laptop and cloud GPU
rows use package-power sources (`powermetrics` on M1 Max, NVML on Modal A10G),
which are a different power boundary and must be footnoted when plotted beside
whole-board hardware rows.

The accepted P3 MCU runs captured INA219 and FNB58 simultaneously. The computed
cross-check is in `results/a19_meter_crosscheck.json`. All nine accepted MCU
cells showed `FNB58 - INA219 < 0`, with implied deltas from about `-3 mW` to
`-6 mW`; those cells are flagged anomalous and excluded from any devkit-overhead
average. Because the upstream FNB58 should normally read above a rail-side
INA219 when both meters share the same power boundary, this dataset is treated
as a calibration/cross-check anomaly rather than a positive devkit-overhead
measurement. The published MCU Wh/1000 values therefore remain INA219-based.

Devkit-level INA219 measurement remains the reproducibility boundary for MCU
results: a reader with the same development board, shunt insertion point, and
telemetry configuration can reproduce the measured board-level energy without
designing a custom production power tree. Per-board shunt wiring is documented
in `docs/hardware/ina219_wiring.md`.

The MCU devkit boundary includes debug-interface state when that interface is
required to run the benchmark protocol. For NUCLEO-F401RE sessions, the serial
protocol uses the board's ST-LINK virtual COM port, so the full-board boundary
is the NUCLEO-F401RE powered through the metered external rail with ST-LINK USB
attached and enumerated. Bench audit data showed that changing ST-LINK/USB state
can move F401RE board power by roughly 28%, so debug-interface state is part of
the disclosed measurement boundary rather than incidental lab setup.

## Launch-Tier MCU Measurement Window

Post 1 launch-tier MCU cells use a short five-inference probe to estimate the
iteration count for a roughly 32-second measured window. The measured window is
then integrated with INA219 rail-side power and the resulting Wh/1000 is
computed over the completed inference count. Published repeat coverage is three
accepted sessions per cell after telemetry-partial and quarantined rows are
excluded.

Diagnostic and variant reruns may use their own 5-warmup plus 20-measured
session protocol and must be labeled separately in their artifacts. Do not mix
that session protocol with the Post 1 launch-tier protocol.

## Determinism

LLM runs use `temperature=0.0`, `top_p=1.0`, and `seed=42`. Experiment 01 records the resolved Ollama model digest in `runs.model_hash` and asserts the Modal digest matches the Mac digest before Modal results are accepted.

## Statistical Bounds Observed

| Target | Tier | p50 ms | p95 ms | p99 ms | p99/p50 | CV |
|---|---:|---:|---:|---:|---:|---:|
| m1-max-64gb | long | 5063.2 | 6020.8 | 6299.1 | 1.24 | 0.082 |
| m1-max-64gb | medium | 3527.5 | 4128.6 | 4254.8 | 1.21 | 0.071 |
| m1-max-64gb | short | 1286.0 | 1477.3 | 1494.9 | 1.16 | 0.064 |
| modal-a10g | long | 1647.5 | 1655.4 | 1657.1 | 1.01 | 0.004 |
| modal-a10g | medium | 1444.6 | 1503.5 | 1551.0 | 1.07 | 0.025 |
| modal-a10g | short | 676.8 | 684.7 | 689.2 | 1.02 | 0.008 |

## Thermal Observations

The sustained M1 Max medium-tier run recorded 137 inferences. Mean duration changed by 15.5% between the first and second halves. Thermal state samples are stored in the Run `extra` JSON.
On this Mac, `machdep.xcpm.cpu_thermal_state` was unavailable, so Experiment 01 uses latency drift as the practical thermal-stability signal and keeps the raw sysctl errors for follow-up.

## Open Questions

- Preserve exact model digests whenever a provider exposes them; plain model names are not enough for cross-target comparisons.
- Decide how the M4 telemetry join should handle LLM runs with long first-token latency and bursty decode phases.
