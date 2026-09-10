# P4 HailoAdapter First Light

## Summary
1. Result: PASS for plumbing; NOT curve-comparable until Brief 2 X-corpus compile.
2. NPU/runtime: HAILO10H / HailoRT HailoRT-CLI version 5.1.1 / firmware 5.1.1 (release,app).
3. Kernel/PCIe: 6.18.29+rpt-rpi-2712 / Speed 8GT/s, Width x1 (downgraded).
4. HEF: `ic_hailo10h.hef` from P4 Brief 2 X-corpus IC prune-40, DFC 5.3.0, HAILO10H; sha256 `66439c498a231da335e019f7ef5a025d85026a70fb6f73afc745ee49858e1699`.
5. Run: `019e608c-e409-7af2-b86d-1dbfd3806273`, 32855 inferences, energy `{'source': 'fnb58', 'wh_per_1000_inferences': 0.0013369944313620962, 'avg_power_w': 4.848252942183484}`.
6. Telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 132, 'ina219': 229}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 132, 'power': 132, 'voltage': 132}, 'ina219': {'current': 229, 'power': 229, 'voltage': 229}}, 'partial': False, 'partial_sources': []}; partial reasons: [].

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
  "hef_name": "ic_hailo10h.hef",
  "hef_path": "/tmp/signal-bench-p4-hailo-019e608c-e409-7af2-b86d-1dbfd3806273/models/ic_hailo10h.hef",
  "hef_source": "P4 Brief 2 X-corpus IC prune-40, DFC 5.3.0, HAILO10H",
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
    "samples": 32855,
    "unique_predictions": 10,
    "value": 0.8700958758179881
  },
  "energy": {
    "avg_power_w": 4.848252942183484,
    "source": "fnb58",
    "wh_per_1000_inferences": 0.0013369944313620962
  },
  "inference_count": 32855,
  "latency_ms": {
    "mean": 0.8091850859838685,
    "p50": 0.81,
    "p99": 0.854
  },
  "output_sanity": {
    "first_output": {
      "argmax": 9,
      "dtype": "float32",
      "max": 0.7058823704719543,
      "min": 0.0,
      "preview": [
        0.007843137718737125,
        0.003921568859368563,
        0.0,
        0.027450982481241226,
        0.011764707043766975,
        0.08235294371843338,
        0.0,
        0.16470588743686676
      ],
      "shape": [
        10
      ],
      "sum": 1.003921627998352,
      "values": [
        0.007843137718737125,
        0.003921568859368563,
        0.0,
        0.027450982481241226,
        0.011764707043766975,
        0.08235294371843338,
        0.0,
        0.16470588743686676,
        0.0,
        0.7058823704719543
      ]
    },
    "garbage": false,
    "unique_argmax_count": 10,
    "valid_outputs": 32855
  },
  "telemetry": {
    "grouped_instants": {
      "bme280": 34,
      "fnb58": 132,
      "ina219": 229
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
        "current": 132,
        "power": 132,
        "voltage": 132
      },
      "ina219": {
        "current": 229,
        "power": 229,
        "voltage": 229
      }
    }
  }
}
```

## First Output

```json
{
  "argmax": 9,
  "dtype": "float32",
  "max": 0.7058823704719543,
  "min": 0.0,
  "preview": [
    0.007843137718737125,
    0.003921568859368563,
    0.0,
    0.027450982481241226,
    0.011764707043766975,
    0.08235294371843338,
    0.0,
    0.16470588743686676
  ],
  "shape": [
    10
  ],
  "sum": 1.003921627998352,
  "values": [
    0.007843137718737125,
    0.003921568859368563,
    0.0,
    0.027450982481241226,
    0.011764707043766975,
    0.08235294371843338,
    0.0,
    0.16470588743686676,
    0.0,
    0.7058823704719543
  ]
}
```

## Scope Flag

Plumbing proven only. This run uses a prebuilt classification HEF and is not curve-comparable. Brief 2 must compile the X-corpus IC/KWS/AD models to HEF before the NPU lands on the hardware curve.
