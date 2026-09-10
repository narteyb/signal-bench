# P4 HailoAdapter First Light

## Summary
1. Result: PASS for plumbing; NOT curve-comparable until Brief 2 X-corpus compile.
2. NPU/runtime: HAILO10H / HailoRT HailoRT-CLI version 5.1.1 / firmware 5.1.1 (release,app).
3. Kernel/PCIe: 6.18.29+rpt-rpi-2712 / Speed 8GT/s, Width x1 (downgraded).
4. HEF: `kws_hailo10h.hef` from P4 Brief 2 X-corpus KWS QAT-weight DS-CNN, DFC 5.3.0, HAILO10H, MLPerf reference-preprocessed eval subset; sha256 `1c1be97cd29c895da0fb72366737473cddcee1fd6920f4f96460691b0a9334cf`.
5. Run: `019e6094-3e09-7671-aae5-0775cf2c321b`, 34548 inferences, energy `{'source': 'fnb58', 'wh_per_1000_inferences': 0.0012958693899420975, 'avg_power_w': 4.823613313570621}`.
6. Telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 134, 'ina219': 231}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 134, 'power': 134, 'voltage': 134}, 'ina219': {'current': 231, 'power': 231, 'voltage': 231}}, 'partial': False, 'partial_sources': []}; partial reasons: [].

## R1 Recon

```text
kernel=6.18.29+rpt-rpi-2712
hailort=HailoRT-CLI version 5.1.1
pyhailort=5.1.1
dev=crw-rw-rw- 1 root root 510, 0 May 25 09:26 /dev/hailo0
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
  "hef_path": "/tmp/signal-bench-p4-hailo-019e6094-3e09-7671-aae5-0775cf2c321b/models/kws_hailo10h.hef",
  "hef_source": "P4 Brief 2 X-corpus KWS QAT-weight DS-CNN, DFC 5.3.0, HAILO10H, MLPerf reference-preprocessed eval subset",
  "input_format_type": "FLOAT32",
  "kernel_version": "6.18.29+rpt-rpi-2712",
  "output_format_type": "FLOAT32",
  "pcie_link": "Speed 8GT/s, Width x1 (downgraded)"
}
```

## Metrics

```json
{
  "accuracy_proxy": {
    "metric": "top1",
    "samples": 34548,
    "unique_predictions": 12,
    "value": 0.810032418663888
  },
  "energy": {
    "avg_power_w": 4.823613313570621,
    "source": "fnb58",
    "wh_per_1000_inferences": 0.0012958693899420975
  },
  "inference_count": 34548,
  "latency_ms": {
    "mean": 0.7686223225657057,
    "p50": 0.769,
    "p99": 0.815
  },
  "output_sanity": {
    "first_output": {
      "argmax": 6,
      "dtype": "float32",
      "max": 1.0,
      "min": 0.0,
      "preview": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0
      ],
      "shape": [
        12
      ],
      "sum": 1.003921627998352,
      "values": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.003921568859368563
      ]
    },
    "garbage": false,
    "unique_argmax_count": 12,
    "valid_outputs": 34548
  },
  "telemetry": {
    "grouped_instants": {
      "bme280": 34,
      "fnb58": 134,
      "ina219": 231
    },
    "partial": false,
    "partial_sources": [],
    "rows": {
      "bme280": {
        "humidity": 34,
        "pressure": 34,
        "temperature": 34
      },
      "fnb58": {
        "current": 134,
        "power": 134,
        "voltage": 134
      },
      "ina219": {
        "current": 231,
        "power": 231,
        "voltage": 231
      }
    }
  }
}
```

## First Output

```json
{
  "argmax": 6,
  "dtype": "float32",
  "max": 1.0,
  "min": 0.0,
  "preview": [
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0
  ],
  "shape": [
    12
  ],
  "sum": 1.003921627998352,
  "values": [
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.003921568859368563
  ]
}
```

## Scope Flag

Plumbing proven only. This run uses a prebuilt classification HEF and is not curve-comparable. Brief 2 must compile the X-corpus IC/KWS/AD models to HEF before the NPU lands on the hardware curve.
