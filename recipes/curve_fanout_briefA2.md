# Curve Fan-Out Brief A2 Recipe

## Telemetry Sources

- `powermetrics`: macOS package-power source in `src/signal_bench/telemetry/sources/powermetrics.py`.
  - Contract: async `start()` / `samples()` / `stop()`.
  - Command: `powermetrics --samplers cpu_power -i 100`.
  - Metric: `TelemetrySample.values["power"]` in watts.
  - Source tag: `powermetrics`.
  - Gate: requires root. Configure passwordless sudo for `/usr/bin/powermetrics --samplers cpu_power *` or provide `SUDO_ASKPASS`; otherwise `start()` raises a source error.
  - Boundary: device package power, window-aggregate Wh/1000 only.

- `nvml`: NVIDIA GPU package-power source in `src/signal_bench/telemetry/sources/nvml.py`.
  - Contract: async `start()` / `samples()` / `stop()`.
  - Library: `pynvml` / `nvidia-ml-py`.
  - Metric: `TelemetrySample.values["power"]` in watts from `nvmlDeviceGetPowerUsage()`.
  - Source tag: `nvml`.
  - Gate: no CUDA/NVML device is a source-start error; zero-power readings are source-data errors.
  - Boundary: GPU package power, window-aggregate Wh/1000 only.

## Modal A10G Runner

Script: `scripts/run_curve_a10g_modal.py`.

- Modal app: `signal-bench-curve-a10g`.
- Image: CUDA 12.4.1 cuDNN runtime on Ubuntu 22.04, Python 3.11.
- Runtime path: TFLite model bytes are staged into the worker, converted to ONNX with `tf2onnx 1.16.1` and opset 17, then run with `onnxruntime-gpu 1.20.1`.
- GPU gate: active providers must include `CUDAExecutionProvider`; CPU-only fallback raises.
- Telemetry: NVML sampled around 10 Hz during the measurement window.
- Timer boundary: `session.run(...)` with input tensor supplied and output tensor returned, matching the input-in/output-out boundary used by the other fast tiers.
- Output: rows are recorded into `data/curve_fanout_briefA.db`; compact run summaries are written to `reports/scratch/curve_a10g_modal_results.json`.

## M1 Max Runner

Script: `scripts/run_curve_m1_cpu.py`.

- Runtime path: local float TFLite models are run with `ai-edge-litert` CPU/XNNPACK. CoreML, ANE, and GPU acceleration are intentionally not used.
- Telemetry: `PowermetricsSource` samples `powermetrics --samplers cpu_power -i 100` while inference runs in a worker thread, keeping the async telemetry pump active.
- Sudo gate: `sudo -n powermetrics --samplers cpu_power -i 100 -n 1` must succeed before a run; otherwise the M1 row is curve-ineligible.
- Timer boundary: `set_tensor -> invoke -> get_tensor`, matching the fast-tier input-in/output-out boundary.
- Output: rows are recorded into `data/curve_fanout_briefA.db`; compact run summaries are written to `reports/scratch/curve_m1_cpu_results.json`.
