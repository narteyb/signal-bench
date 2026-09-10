# P4 HailoAdapter First Light

## Summary
1. Result: PASS for plumbing; NOT curve-comparable until Brief 2 X-corpus compile.
2. NPU/runtime: HAILO10H / HailoRT HailoRT-CLI version 5.1.1 / firmware 5.1.1 (release,app).
3. Kernel/PCIe: 6.18.29+rpt-rpi-2712 / Speed 8GT/s, Width x1 (downgraded).
4. HEF: `ic_hailo10h.hef` from P4 Brief 2 X-corpus IC prune-40, DFC 5.3.0, HAILO10H; timer-boundary aligned rerun; sha256 `66439c498a231da335e019f7ef5a025d85026a70fb6f73afc745ee49858e1699`.
5. Run: `019e62c6-0978-7530-9b11-ce7684ac6508`, 31818 inferences, energy `{'source': 'fnb58', 'wh_per_1000_inferences': 0.001358796492002324, 'avg_power_w': 4.92352358077688}`.
6. Telemetry: {'grouped_instants': {'bme280': 32, 'fnb58': 128}, 'rows': {'bme280': {'humidity': 32, 'pressure': 32, 'temperature': 32}, 'fnb58': {'current': 128, 'power': 128, 'voltage': 128}}, 'partial': False, 'partial_sources': []}; partial reasons: [].

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
  "hef_name": "ic_hailo10h.hef",
  "hef_path": "/tmp/signal-bench-p4-hailo-019e62c6-0978-7530-9b11-ce7684ac6508/models/ic_hailo10h.hef",
  "hef_source": "P4 Brief 2 X-corpus IC prune-40, DFC 5.3.0, HAILO10H; timer-boundary aligned rerun",
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
    "samples": 31818,
    "unique_predictions": 10,
    "value": 0.8700106857753472
  },
  "energy": {
    "avg_power_w": 4.92352358077688,
    "source": "fnb58",
    "wh_per_1000_inferences": 0.001358796492002324
  },
  "inference_count": 31818,
  "latency_ms": {
    "mean": 0.8345768432962474,
    "p50": 0.838,
    "p99": 0.8828300000000018
  },
  "output_sanity": {
    "first_output": {
      "argmax": 9,
      "dtype": "uint8",
      "max": 180.0,
      "min": 0.0,
      "preview": [
        2,
        1,
        0,
        7,
        3,
        21,
        0,
        42
      ],
      "shape": [
        10
      ],
      "sum": 256.0,
      "values": [
        2,
        1,
        0,
        7,
        3,
        21,
        0,
        42,
        0,
        180
      ]
    },
    "garbage": false,
    "unique_argmax_count": 10,
    "valid_outputs": 31818
  },
  "telemetry": {
    "grouped_instants": {
      "bme280": 32,
      "fnb58": 128
    },
    "partial": false,
    "partial_sources": [],
    "rows": {
      "bme280": {
        "humidity": 32,
        "pressure": 32,
        "temperature": 32
      },
      "fnb58": {
        "current": 128,
        "power": 128,
        "voltage": 128
      }
    }
  }
}
```

## First Output

```json
{
  "argmax": 9,
  "dtype": "uint8",
  "max": 180.0,
  "min": 0.0,
  "preview": [
    2,
    1,
    0,
    7,
    3,
    21,
    0,
    42
  ],
  "shape": [
    10
  ],
  "sum": 256.0,
  "values": [
    2,
    1,
    0,
    7,
    3,
    21,
    0,
    42,
    0,
    180
  ]
}
```

## Scope Flag

Plumbing proven only. This run uses a prebuilt classification HEF and is not curve-comparable. Brief 2 must compile the X-corpus IC/KWS/AD models to HEF before the NPU lands on the hardware curve.
