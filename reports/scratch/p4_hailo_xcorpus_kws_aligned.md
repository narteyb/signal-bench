# P4 HailoAdapter First Light

## Summary
1. Result: PASS for plumbing; NOT curve-comparable until Brief 2 X-corpus compile.
2. NPU/runtime: HAILO10H / HailoRT HailoRT-CLI version 5.1.1 / firmware 5.1.1 (release,app).
3. Kernel/PCIe: 6.18.29+rpt-rpi-2712 / Speed 8GT/s, Width x1 (downgraded).
4. HEF: `kws_hailo10h.hef` from P4 Brief 2 X-corpus KWS QAT-weight DS-CNN, DFC 5.3.0, HAILO10H, MLPerf reference-preprocessed eval subset; timer-boundary aligned rerun; sha256 `1c1be97cd29c895da0fb72366737473cddcee1fd6920f4f96460691b0a9334cf`.
5. Run: `019e62c7-2bb3-75e3-8edb-a94e7fc6800e`, 34247 inferences, energy `{'source': 'fnb58', 'wh_per_1000_inferences': 0.0012994644187931022, 'avg_power_w': 4.953334522888537}`.
6. Telemetry: {'grouped_instants': {'bme280': 33, 'fnb58': 131}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'fnb58': {'current': 131, 'power': 131, 'voltage': 131}}, 'partial': False, 'partial_sources': []}; partial reasons: [].

## R1 Recon

```text
kernel=6.18.29+rpt-rpi-2712
hailort=HailoRT-CLI version 5.1.1
pyhailort=5.1.1
dev=crw-rw-rw- 1 root root 510, 0 May 25 22:27 /dev/hailo0
identify<<EOF
Executing on device: 0001:01:00.0
Identifying board
Control Protocol Version: 2
Firmware Version: 5.1.1 (release,app)
Logger Version: 0
Device Architecture: HAILO10H


EOF
pcie<<EOF
0001:01:00.0 Co-processor [0b40]: Hailo Technologies Ltd. Hailo-10H AI Processor [1e60:45c4] (rev 01)
	Subsystem: Hailo Technologies Ltd. Hailo-10H AI Processor [1e60:45c4]
		LnkSta:	Speed 8GT/s, Width x1 (downgraded)

EOF
```

## Adapter Contract

- Adapter methods matched existing `Adapter`: `prepare(run_id)`, `warmup()`, `measure(task, iterations)`, `read_thermal()`, `os_info()`, `teardown()`.
- Telemetry uses the existing async source contract: `start()`, `samples()` async iterator, `stop()`, grouped `TelemetrySample.values`.
- DB writes use existing `runs`, `results`, `telemetry_samples`, `targets`, and `tasks`; telemetry column is `metric`.

## Run Metadata

```json
{
  "adapter": "HailoAdapter",
  "batch_size": "1",
  "hailo_architecture": "HAILO10H",
  "hailo_firmware_version": "5.1.1 (release,app)",
  "hailort_version": "HailoRT-CLI version 5.1.1",
  "hef_name": "kws_hailo10h.hef",
  "hef_path": "/tmp/signal-bench-p4-hailo-019e62c7-2bb3-75e3-8edb-a94e7fc6800e/models/kws_hailo10h.hef",
  "hef_source": "P4 Brief 2 X-corpus KWS QAT-weight DS-CNN, DFC 5.3.0, HAILO10H, MLPerf reference-preprocessed eval subset; timer-boundary aligned rerun",
  "input_format_type": "FLOAT32",
  "kernel_version": "6.18.29+rpt-rpi-2712",
  "output_format_type": "UINT8",
  "pcie_link": "Speed 8GT/s, Width x1 (downgraded)"
}
```

## Metrics

```json
{
  "accuracy_proxy": {
    "metric": "top1",
    "samples": 34247,
    "unique_predictions": 12,
    "value": 0.8100271556632698
  },
  "energy": {
    "avg_power_w": 4.953334522888537,
    "source": "fnb58",
    "wh_per_1000_inferences": 0.0012994644187931022
  },
  "inference_count": 34247,
  "latency_ms": {
    "mean": 0.7893082313779309,
    "p50": 0.791,
    "p99": 0.84
  },
  "output_sanity": {
    "first_output": {
      "argmax": 6,
      "dtype": "uint8",
      "max": 255.0,
      "min": 0.0,
      "preview": [
        0,
        0,
        0,
        0,
        0,
        0,
        255,
        0
      ],
      "shape": [
        12
      ],
      "sum": 256.0,
      "values": [
        0,
        0,
        0,
        0,
        0,
        0,
        255,
        0,
        0,
        0,
        0,
        1
      ]
    },
    "garbage": false,
    "unique_argmax_count": 12,
    "valid_outputs": 34247
  },
  "telemetry": {
    "grouped_instants": {
      "bme280": 33,
      "fnb58": 131
    },
    "partial": false,
    "partial_sources": [],
    "rows": {
      "bme280": {
        "humidity": 33,
        "pressure": 33,
        "temperature": 33
      },
      "fnb58": {
        "current": 131,
        "power": 131,
        "voltage": 131
      }
    }
  }
}
```

## First Output

```json
{
  "argmax": 6,
  "dtype": "uint8",
  "max": 255.0,
  "min": 0.0,
  "preview": [
    0,
    0,
    0,
    0,
    0,
    0,
    255,
    0
  ],
  "shape": [
    12
  ],
  "sum": 256.0,
  "values": [
    0,
    0,
    0,
    0,
    0,
    0,
    255,
    0,
    0,
    0,
    0,
    1
  ]
}
```

## Scope Flag

Plumbing proven only. This run uses a prebuilt classification HEF and is not curve-comparable. Brief 2 must compile the X-corpus IC/KWS/AD models to HEF before the NPU lands on the hardware curve.
