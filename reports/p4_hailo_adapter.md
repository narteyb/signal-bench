# P4 HailoAdapter First Light

## Summary
1. Result: PASS for plumbing; NOT curve-comparable until Brief 2 X-corpus compile.
2. NPU/runtime: HAILO10H / HailoRT HailoRT-CLI version 5.1.1 / firmware 5.1.1 (release,app).
3. Kernel/PCIe: 6.18.29+rpt-rpi-2712 / Speed 8GT/s, Width x1 (downgraded).
4. HEF: `resnet_v1_50_h10.hef` from Model-Zoo-prebuilt on Pi; remote path /usr/share/hailo-models/resnet_v1_50_h10.hef; package owner: hailo-models: /usr/share/hailo-models/resnet_v1_50_h10.hef; sha256 `1f6fecf62263f7bea9f76b1caff406ed899bc355dae92ab738f1aeaead49c857`.
5. Run: `019e601e-4c9b-7150-aa64-7fe7fe61800e`, 4209 inferences, energy `{'source': 'fnb58', 'wh_per_1000_inferences': 0.01012511105312056, 'avg_power_w': 4.88494015480352}`.
6. Telemetry: {'grouped_instants': {'bme280': 32, 'fnb58': 126, 'ina219': 217}, 'rows': {'bme280': {'humidity': 32, 'pressure': 32, 'temperature': 32}, 'fnb58': {'current': 126, 'power': 126, 'voltage': 126}, 'ina219': {'current': 217, 'power': 217, 'voltage': 217}}, 'partial': False, 'partial_sources': []}; partial reasons: [].

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
  "hef_name": "resnet_v1_50_h10.hef",
  "hef_path": "/usr/share/hailo-models/resnet_v1_50_h10.hef",
  "hef_source": "Model-Zoo-prebuilt on Pi; remote path /usr/share/hailo-models/resnet_v1_50_h10.hef; package owner: hailo-models: /usr/share/hailo-models/resnet_v1_50_h10.hef",
  "input_format_type": "FLOAT32",
  "kernel_version": "6.18.29+rpt-rpi-2712",
  "output_format_type": "UINT8",
  "pcie_link": "Speed 8GT/s, Width x1 (downgraded)"
}
```

## Metrics

```json
{
  "energy": {
    "avg_power_w": 4.88494015480352,
    "source": "fnb58",
    "wh_per_1000_inferences": 0.01012511105312056
  },
  "inference_count": 4209,
  "latency_ms": {
    "mean": 6.797571869802804,
    "p50": 6.788,
    "p99": 6.96484
  },
  "output_sanity": {
    "first_output": {
      "argmax": 644,
      "dtype": "uint8",
      "max": 20.0,
      "min": 0.0,
      "preview": [
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0
      ],
      "shape": [
        1,
        1,
        1000
      ],
      "sum": 207.0
    },
    "garbage": false,
    "unique_argmax_count": 1,
    "valid_outputs": 4209
  },
  "telemetry": {
    "grouped_instants": {
      "bme280": 32,
      "fnb58": 126,
      "ina219": 217
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
        "current": 126,
        "power": 126,
        "voltage": 126
      },
      "ina219": {
        "current": 217,
        "power": 217,
        "voltage": 217
      }
    }
  }
}
```

## First Output

```json
{
  "argmax": 644,
  "dtype": "uint8",
  "max": 20.0,
  "min": 0.0,
  "preview": [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0
  ],
  "shape": [
    1,
    1,
    1000
  ],
  "sum": 207.0
}
```

## Scope Flag

Plumbing proven only. This run uses a prebuilt classification HEF and is not curve-comparable. Brief 2 must compile the X-corpus IC/KWS/AD models to HEF before the NPU lands on the hardware curve.
