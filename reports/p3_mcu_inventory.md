
## Nano33 energy anomaly note

- 2026-05-29: Nano33 session-3 energy runs `019e7543-37c3-7e32-bd60-339408178788`, `019e7545-f8a5-75e0-a20d-857ae690429e`, and `019e7548-0873-7571-99dd-e67e5eb23723` are quarantined for energy only; latency remains usable.
- Root cause: after the ESP32-S3 to Nano33 swap, the active Nano33 load bypassed the FNB58/INA219 metered rail, consistent with unmetered USB VBUS powering the board while the serial/flash cable was attached. The fixed setup routes board supply current through FNB58 and the INA219 shunt; keep USB VBUS isolated or metered on the next board swap.
- Fixed-path smoke check `019e7564-8561-7cc3-b6fb-9359503a5a88`: FNB58 averaged 0.03508 W and INA219 averaged 0.03804 W on KWS, confirming meter agreement after rewiring. This run is diagnostic only because INA219 coverage made it `telemetry_partial=true`.
- Corrected Nano33 session-3 A03 energy runs: AD `019e7567-3aea-7621-9671-32874cf4529e`, IC `019e7569-6922-7123-be2a-5478fcbd3e5f`, KWS `019e756b-3d0c-7610-be25-85b897d45d51`; all have `telemetry_partial=false`.

## F401RE/IC energy boundary note

- 2026-05-29: F401RE/IC baseline run `019e5db4-e375-7942-9182-e4fef42ce9c7` is quarantined for energy only; latency remains usable.
- Evidence: the baseline averages `0.07052 W` on INA219 and `0.06729 W` on FNB58, while the full-board reruns average `0.3395-0.3421 W` on INA219 and `0.3336-0.3401 W` on FNB58. The baseline predates the full-board metered-rail discipline and sits on a non-conforming MCU-only power boundary.
- Conforming F401RE/IC energy runs: `019e7598-6637-7dd0-974b-881675b0bedc`, `019e759a-52b9-71e0-8769-486b450e2244`, and `019e75fe-9c3b-7061-9423-2831fac5798d`; all have `telemetry_partial=false` and FNB58/INA219 agreement within roughly 1-2%.

## P3 MCU repeat coverage audit

Audit date: 2026-05-29.

Repeat requirement: three eligible runs per target/task cell. Eligible means `status=completed`, `finished_at` present, and `telemetry_partial=false`.

| target | task | required | eligible | missing | extra | ineligible | action |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| esp32s3 | kws | 3 | 3 | 0 | 0 | 0 | complete |
| esp32s3 | ic | 3 | 3 | 0 | 0 | 0 | complete |
| esp32s3 | ad | 3 | 3 | 0 | 0 | 1 | complete; one failed attempt ignored |
| nano33 | kws | 3 | 6 | 0 | 3 | 1 | complete; surplus/diagnostic runs retained |
| nano33 | ic | 3 | 4 | 0 | 1 | 0 | complete |
| nano33 | ad | 3 | 4 | 0 | 1 | 0 | complete |
| f401re | kws | 3 | 3 | 0 | 0 | 1 | complete; one partial diagnostic ignored |
| f401re | ic | 3 | 4 | 0 | 1 | 0 | complete; baseline energy quarantined, 3 conforming energy runs retained |
| f401re | ad | 3 | 3 | 0 | 0 | 1 | complete; one partial diagnostic ignored |

F401RE/IC is now closed with four latency-valid runs and three conforming full-board energy runs. Baseline run `019e5db4-e375-7942-9182-e4fef42ce9c7` remains in latency aggregation but its energy is excluded. The full-board energy set is `019e7598-6637-7dd0-974b-881675b0bedc`, `019e759a-52b9-71e0-8769-486b450e2244`, and `019e75fe-9c3b-7061-9423-2831fac5798d`.

## esp32s3 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e5d8a-b23b-7c12-a163-1a0d0496eaa9
- latency_ms: {'mean_ms': 106.49761948249619, 'p50_ms': 106.496, 'p99_ms': 106.523}
- Wh/1000: 0.013221435833756132
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 282, 'ina219': 487}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 282, 'power': 282, 'voltage': 282}, 'ina219': {'current': 487, 'power': 487, 'voltage': 487}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.2480974124809741, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 430464, 'firmware_elf_bytes': 12602896, 'ram_used_bytes': 68848, 'ram_limit_bytes': 327680, 'flash_used_bytes': 430101, 'flash_limit_bytes': 3342336}

## esp32s3 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e5d8c-b9d7-76c1-ad1d-320a29516ca4
- latency_ms: {'mean_ms': 551.064296875, 'p50_ms': 551.0625, 'p99_ms': 551.08}
- Wh/1000: 0.06763141712022572
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 284, 'ina219': 489}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 284, 'power': 284, 'voltage': 284}, 'ina219': {'current': 489, 'power': 489, 'voltage': 489}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.828125, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 501200, 'firmware_elf_bytes': 12514580, 'ram_used_bytes': 85232, 'ram_limit_bytes': 327680, 'flash_used_bytes': 500829, 'flash_limit_bytes': 3342336}

## esp32s3 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e5d8e-c5c3-7fa0-b798-93347e4afa0f
- latency_ms: {'mean_ms': 11.721601508801342, 'p50_ms': 11.723, 'p99_ms': 11.727}
- Wh/1000: 0.0014400131898109345
- telemetry: {'grouped_instants': {'bme280': 73, 'fnb58': 292, 'ina219': 499}, 'rows': {'bme280': {'humidity': 73, 'pressure': 73, 'temperature': 73}, 'fnb58': {'current': 292, 'power': 292, 'voltage': 292}, 'ina219': {'current': 499, 'power': 499, 'voltage': 499}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6944351324170298, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 503264, 'firmware_elf_bytes': 11902276, 'ram_used_bytes': 44268, 'ram_limit_bytes': 327680, 'flash_used_bytes': 502905, 'flash_limit_bytes': 3342336}

## nano33 / kws

- status: fail
- corpus_tag: N3
- footprint: None

## nano33 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e5da5-52ee-7d03-800e-9737850b6d96
- latency_ms: {'mean_ms': 224.21490095846644, 'p50_ms': 224.225, 'p99_ms': 224.25164}
- Wh/1000: 0.002382435086971953
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 284, 'ina219': 491}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 284, 'power': 284, 'voltage': 284}, 'ina219': {'current': 491, 'power': 491, 'voltage': 491}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.2523961661341853, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 209560, 'firmware_elf_bytes': 366632, 'ram_used_bytes': 93648, 'ram_limit_bytes': 262144, 'flash_used_bytes': 209560, 'flash_limit_bytes': 983040}

## nano33 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e5da7-ef3e-7830-94a8-2ef6f6845b8e
- latency_ms: {'mean_ms': 224.21335782747605, 'p50_ms': 224.225, 'p99_ms': 224.255}
- Wh/1000: 0.002362934765708199
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 284, 'ina219': 490}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 284, 'power': 284, 'voltage': 284}, 'ina219': {'current': 490, 'power': 490, 'voltage': 490}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.2523961661341853, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 209560, 'firmware_elf_bytes': 366632, 'ram_used_bytes': 93648, 'ram_limit_bytes': 262144, 'flash_used_bytes': 209560, 'flash_limit_bytes': 983040}

## nano33 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e5daa-6c50-77d2-a24c-6ff624d22cc5
- latency_ms: {'mean_ms': 1232.7513157894737, 'p50_ms': 1232.807, 'p99_ms': 1233.49996}
- Wh/1000: 0.01369833535575047
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 282, 'ina219': 488}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 282, 'power': 282, 'voltage': 282}, 'ina219': {'current': 488, 'power': 488, 'voltage': 488}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8245614035087719, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 280464, 'firmware_elf_bytes': 436696, 'ram_used_bytes': 110032, 'ram_limit_bytes': 262144, 'flash_used_bytes': 280464, 'flash_limit_bytes': 983040}

## nano33 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e5dac-d497-7a52-b3a9-ba11b3f2185f
- latency_ms: {'mean_ms': 12.422005322924061, 'p50_ms': 12.421, 'p99_ms': 12.448}
- Wh/1000: 0.00018893861288541919
- telemetry: {'grouped_instants': {'bme280': 104, 'fnb58': 415, 'ina219': 708}, 'rows': {'bme280': {'humidity': 104, 'pressure': 104, 'temperature': 104}, 'fnb58': {'current': 415, 'power': 415, 'voltage': 415}, 'ina219': {'current': 708, 'power': 708, 'voltage': 708}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6946021747047395, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 282096, 'firmware_elf_bytes': 426492, 'ram_used_bytes': 69072, 'ram_limit_bytes': 262144, 'flash_used_bytes': 282096, 'flash_limit_bytes': 983040}

## f401re / kws

- status: pass
- corpus_tag: N3
- run_id: 019e5db3-0d4d-72e1-8033-380875e45cf3
- latency_ms: {'mean_ms': 158.9303968253968, 'p50_ms': 158.925, 'p99_ms': 158.9846}
- Wh/1000: 0.0032401868203577704
- telemetry: {'grouped_instants': {'bme280': 72, 'fnb58': 287, 'ina219': 495}, 'rows': {'bme280': {'humidity': 72, 'pressure': 72, 'temperature': 72}, 'fnb58': {'current': 287, 'power': 287, 'voltage': 287}, 'ina219': {'current': 495, 'power': 495, 'voltage': 495}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.2471655328798186, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 135596, 'firmware_elf_bytes': 205036, 'ram_used_bytes': 51116, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135136, 'flash_limit_bytes': 524288}

## f401re / ic

- status: pass
- corpus_tag: N3
- run_id: 019e5db4-e375-7942-9182-e4fef42ce9c7
- latency_ms: {'mean_ms': 755.3910322580645, 'p50_ms': 755.389, 'p99_ms': 755.44104}
- Wh/1000: 0.014801957386499393
- energy_quarantined: true - non-conforming pre-discipline power boundary; latency remains valid.
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 282, 'ina219': 485}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 282, 'power': 282, 'voltage': 282}, 'ina219': {'current': 485, 'power': 485, 'voltage': 485}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8279569892473119, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 206644, 'firmware_elf_bytes': 274112, 'ram_used_bytes': 67500, 'ram_limit_bytes': 98304, 'flash_used_bytes': 206184, 'flash_limit_bytes': 524288}

## f401re / ad

- status: fail
- corpus_tag: N3
- run_id: 019e5db6-a631-7210-85dd-7cc33f0e0049
- latency_ms: {'mean_ms': 8.1367615, 'p50_ms': 8.136, 'p99_ms': 8.181}
- Wh/1000: 0.00023600492593750015
- telemetry: {'grouped_instants': {'fnb58': 381, 'ina219': 762}, 'rows': {'fnb58': {'current': 381, 'power': 381, 'voltage': 381}, 'ina219': {'current': 762, 'power': 762, 'voltage': 762}}, 'partial': True, 'partial_sources': ['bme280']}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6945555625, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 209692, 'firmware_elf_bytes': 266664, 'ram_used_bytes': 26540, 'ram_limit_bytes': 98304, 'flash_used_bytes': 209224, 'flash_limit_bytes': 524288}

## Accepted P3 MCU matrix

These are the latest non-partial pass rows for each target/workload. Earlier entries in this file include diagnostic reruns and rejected attempts.

| target | task | run_id | mean_ms | p50_ms | p99_ms | Wh/1000 | telemetry grouped instants | flash/RAM bytes |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| esp32s3 | kws | 019e5d8a-b23b-7c12-a163-1a0d0496eaa9 | 106.497619 | 106.496 | 106.523 | 0.013221435834 | ina219=487, fnb58=282, bme280=71 | 430101 / 68848 |
| esp32s3 | ic | 019e5d8c-b9d7-76c1-ad1d-320a29516ca4 | 551.064297 | 551.0625 | 551.08 | 0.06763141712 | ina219=489, fnb58=284, bme280=71 | 500829 / 85232 |
| esp32s3 | ad | 019e5d8e-c5c3-7fa0-b798-93347e4afa0f | 11.721602 | 11.723 | 11.727 | 0.00144001319 | ina219=499, fnb58=292, bme280=73 | 502905 / 44268 |
| nano33 | kws | 019e5da7-ef3e-7830-94a8-2ef6f6845b8e | 224.213358 | 224.225 | 224.255 | 0.002362934766 | ina219=490, fnb58=284, bme280=71 | 209560 / 93648 |
| nano33 | ic | 019e5daa-6c50-77d2-a24c-6ff624d22cc5 | 1232.751316 | 1232.807 | 1233.49996 | 0.013698335356 | ina219=488, fnb58=282, bme280=71 | 280464 / 110032 |
| nano33 | ad | 019e5dac-d497-7a52-b3a9-ba11b3f2185f | 12.422005 | 12.421 | 12.448 | 0.000188938613 | ina219=708, fnb58=415, bme280=104 | 282096 / 69072 |
| f401re | kws | 019e5db3-0d4d-72e1-8033-380875e45cf3 | 158.930397 | 158.925 | 158.9846 | 0.00324018682 | ina219=495, fnb58=287, bme280=72 | 135136 / 51116 |
| f401re | ic | 019e5db4-e375-7942-9182-e4fef42ce9c7 | 755.391032 | 755.389 | 755.44104 | 0.014801957386 | ina219=485, fnb58=282, bme280=71 | 206184 / 67500 |
| f401re | ad | 019e5dc5-11f9-7a41-8fd5-543d80de7eaa | 8.13676 | 8.136 | 8.18001 | 0.000141697492 | ina219=674, fnb58=390, bme280=98 | 209224 / 26540 |

## f401re / ad

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ad

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ad

- status: pass
- corpus_tag: N3
- run_id: 019e5dc5-11f9-7a41-8fd5-543d80de7eaa
- latency_ms: {'mean_ms': 8.1367595, 'p50_ms': 8.136, 'p99_ms': 8.18001}
- Wh/1000: 0.00014169749156249986
- telemetry: {'grouped_instants': {'bme280': 98, 'fnb58': 390, 'ina219': 674}, 'rows': {'bme280': {'humidity': 98, 'pressure': 98, 'temperature': 98}, 'fnb58': {'current': 390, 'power': 390, 'voltage': 390}, 'ina219': {'current': 674, 'power': 674, 'voltage': 674}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6945555625, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 209692, 'firmware_elf_bytes': 266664, 'ram_used_bytes': 26540, 'ram_limit_bytes': 98304, 'flash_used_bytes': 209224, 'flash_limit_bytes': 524288}

## Final accepted P3 MCU matrix

These are the latest non-partial pass rows for each target/workload. Earlier entries in this file include diagnostic reruns and rejected attempts.

| target | task | run_id | mean_ms | p50_ms | p99_ms | Wh/1000 | telemetry grouped instants | flash/RAM bytes |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| esp32s3 | kws | 019e5d8a-b23b-7c12-a163-1a0d0496eaa9 | 106.497619 | 106.496 | 106.523 | 0.013221435834 | ina219=487, fnb58=282, bme280=71 | 430101 / 68848 |
| esp32s3 | ic | 019e5d8c-b9d7-76c1-ad1d-320a29516ca4 | 551.064297 | 551.0625 | 551.08 | 0.06763141712 | ina219=489, fnb58=284, bme280=71 | 500829 / 85232 |
| esp32s3 | ad | 019e5d8e-c5c3-7fa0-b798-93347e4afa0f | 11.721602 | 11.723 | 11.727 | 0.00144001319 | ina219=499, fnb58=292, bme280=73 | 502905 / 44268 |
| nano33 | kws | 019e5da7-ef3e-7830-94a8-2ef6f6845b8e | 224.213358 | 224.225 | 224.255 | 0.002362934766 | ina219=490, fnb58=284, bme280=71 | 209560 / 93648 |
| nano33 | ic | 019e5daa-6c50-77d2-a24c-6ff624d22cc5 | 1232.751316 | 1232.807 | 1233.49996 | 0.013698335356 | ina219=488, fnb58=282, bme280=71 | 280464 / 110032 |
| nano33 | ad | 019e5dac-d497-7a52-b3a9-ba11b3f2185f | 12.422005 | 12.421 | 12.448 | 0.000188938613 | ina219=708, fnb58=415, bme280=104 | 282096 / 69072 |
| f401re | kws | 019e5db3-0d4d-72e1-8033-380875e45cf3 | 158.930397 | 158.925 | 158.9846 | 0.00324018682 | ina219=495, fnb58=287, bme280=72 | 135136 / 51116 |
| f401re | ic | 019e5db4-e375-7942-9182-e4fef42ce9c7 | 755.391032 | 755.389 | 755.44104 | 0.014801957386 | ina219=485, fnb58=282, bme280=71 | 206184 / 67500 |
| f401re | ad | 019e5dc5-11f9-7a41-8fd5-543d80de7eaa | 8.13676 | 8.136 | 8.18001 | 0.000141697492 | ina219=674, fnb58=390, bme280=98 | 209224 / 26540 |

## esp32s3 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e6532-b4fd-7310-8cf7-4eda7c26f834
- latency_ms: {'mean_ms': 11.72172863953062, 'p50_ms': 11.723, 'p99_ms': 11.727}
- Wh/1000: 4.2304194678727105e-06
- telemetry: {'grouped_instants': {'bme280': 34, 'ina219': 231}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'ina219': {'current': 231, 'power': 231, 'voltage': 231}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6946279231383248, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 503264, 'firmware_elf_bytes': 11902276, 'ram_used_bytes': 44268, 'ram_limit_bytes': 327680, 'flash_used_bytes': 502905, 'flash_limit_bytes': 3342336}

## esp32s3 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e6538-f7b8-76a2-b79c-8353623df07c
- latency_ms: {'mean_ms': 11.721719838650532, 'p50_ms': 11.723, 'p99_ms': 11.727}
- Wh/1000: 0.001428802173328444
- telemetry: {'grouped_instants': {'bme280': 34, 'ina219': 231}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'ina219': {'current': 231, 'power': 231, 'voltage': 231}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6946279231383248, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 503264, 'firmware_elf_bytes': 11902276, 'ram_used_bytes': 44268, 'ram_limit_bytes': 327680, 'flash_used_bytes': 502905, 'flash_limit_bytes': 3342336}

## esp32s3 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e653a-5889-71d1-8252-562d3a20e2e2
- latency_ms: {'mean_ms': 551.0667966101695, 'p50_ms': 551.06, 'p99_ms': 551.20054}
- Wh/1000: 0.06741579500941615
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 227}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 227, 'power': 227, 'voltage': 227}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8305084745762712, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 501200, 'firmware_elf_bytes': 12514580, 'ram_used_bytes': 85232, 'ram_limit_bytes': 327680, 'flash_used_bytes': 500829, 'flash_limit_bytes': 3342336}

## esp32s3 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e653b-a89f-72b2-a648-adc974d864fc
- latency_ms: {'mean_ms': 106.49727333333334, 'p50_ms': 106.496, 'p99_ms': 106.52401}
- Wh/1000: 0.013176856153703693
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 224}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 224, 'power': 224, 'voltage': 224}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.25, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 430464, 'firmware_elf_bytes': 12602896, 'ram_used_bytes': 68848, 'ram_limit_bytes': 327680, 'flash_used_bytes': 430101, 'flash_limit_bytes': 3342336}

## f401re / ad

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ad

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ad

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ad

- status: fail
- corpus_tag: N3
- footprint: None

## nano33 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e6748-d2ff-7271-90c9-fe0415802f39
- latency_ms: {'mean_ms': 12.422186335403726, 'p50_ms': 12.421, 'p99_ms': 12.448}
- Wh/1000: 0.00018891270552967557
- telemetry: {'grouped_instants': {'bme280': 48, 'ina219': 331}, 'rows': {'bme280': {'humidity': 48, 'pressure': 48, 'temperature': 48}, 'ina219': {'current': 331, 'power': 331, 'voltage': 331}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6947895769839126, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 282096, 'firmware_elf_bytes': 426492, 'ram_used_bytes': 69072, 'ram_limit_bytes': 262144, 'flash_used_bytes': 282096, 'flash_limit_bytes': 983040}

## nano33 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e674a-f6b6-7092-a5d0-b84111bc0858
- latency_ms: {'mean_ms': 1232.611153846154, 'p50_ms': 1232.6125000000002, 'p99_ms': 1233.0635}
- Wh/1000: 0.013716473963675204
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 224}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 224, 'power': 224, 'voltage': 224}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8461538461538461, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 280464, 'firmware_elf_bytes': 436696, 'ram_used_bytes': 110032, 'ram_limit_bytes': 262144, 'flash_used_bytes': 280464, 'flash_limit_bytes': 983040}

## nano33 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e674c-cd81-7243-9470-a0d817a5b26d
- latency_ms: {'mean_ms': 224.21984615384616, 'p50_ms': 224.222, 'p99_ms': 224.23758}
- Wh/1000: 0.0023789786596736585
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 223}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 223, 'power': 223, 'voltage': 223}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24475524475524477, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 209560, 'firmware_elf_bytes': 366632, 'ram_used_bytes': 93648, 'ram_limit_bytes': 262144, 'flash_used_bytes': 209560, 'flash_limit_bytes': 983040}

## f401re / kws

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / kws

- status: fail
- corpus_tag: N3
- run_id: 019e71d5-1aba-7d52-870e-36d09b4e05a3
- latency_ms: {'mean_ms': 158.92600000000002, 'p50_ms': 158.924, 'p99_ms': 158.96123999999998}
- Wh/1000: 0.02817373833333332
- telemetry: {'grouped_instants': {'bme280': 1, 'ina219': 6}, 'rows': {'bme280': {'humidity': 1, 'pressure': 1, 'temperature': 1}, 'ina219': {'current': 6, 'power': 6, 'voltage': 6}}, 'partial': True, 'partial_sources': ['bme280', 'ina219']}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.3333333333333333, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 131492, 'firmware_elf_bytes': 201108, 'ram_used_bytes': 51396, 'ram_limit_bytes': 98304, 'flash_used_bytes': 131024, 'flash_limit_bytes': 524288}

## f401re / ad

- status: pass
- corpus_tag: N3
- run_id: 019e71d6-2d18-70b2-aef5-0d594ad79a56
- latency_ms: {'mean_ms': 8.13998579401319, 'p50_ms': 8.138, 'p99_ms': 8.184}
- Wh/1000: 0.001244634707565251
- telemetry: {'grouped_instants': {'bme280': 47, 'ina219': 328}, 'rows': {'bme280': {'humidity': 47, 'pressure': 47, 'temperature': 47}, 'ina219': {'current': 328, 'power': 328, 'voltage': 328}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.8001014713343481, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 215100, 'firmware_elf_bytes': 270928, 'ram_used_bytes': 26820, 'ram_limit_bytes': 98304, 'flash_used_bytes': 214640, 'flash_limit_bytes': 524288}

## f401re / kws

- status: pass
- corpus_tag: N3
- run_id: 019e71d7-9146-7c70-9034-a703f581fd72
- latency_ms: {'mean_ms': 158.9282475247525, 'p50_ms': 158.9255, 'p99_ms': 158.98199}
- Wh/1000: 0.017471541626787653
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 229}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 229, 'power': 229, 'voltage': 229}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.20297029702970298, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 139836, 'firmware_elf_bytes': 209300, 'ram_used_bytes': 51396, 'ram_limit_bytes': 98304, 'flash_used_bytes': 139368, 'flash_limit_bytes': 524288}

## f401re / ad

- status: pass
- corpus_tag: N3
- run_id: 019e71dd-d72d-74d1-9087-1efa126593cb
- latency_ms: {'mean_ms': 8.139935312024352, 'p50_ms': 8.138, 'p99_ms': 8.184}
- Wh/1000: 0.001248620438933987
- telemetry: {'grouped_instants': {'bme280': 47, 'ina219': 329}, 'rows': {'bme280': {'humidity': 47, 'pressure': 47, 'temperature': 47}, 'ina219': {'current': 329, 'power': 329, 'voltage': 329}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.8001014713343481, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 215100, 'firmware_elf_bytes': 270928, 'ram_used_bytes': 26820, 'ram_limit_bytes': 98304, 'flash_used_bytes': 214640, 'flash_limit_bytes': 524288}

## f401re / kws

- status: pass
- corpus_tag: N3
- run_id: 019e71df-33a5-7543-b033-19e93aa72de1
- latency_ms: {'mean_ms': 158.92832673267327, 'p50_ms': 158.924, 'p99_ms': 158.97798}
- Wh/1000: 0.017489053319581963
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 230}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 230, 'power': 230, 'voltage': 230}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.20297029702970298, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 139836, 'firmware_elf_bytes': 209300, 'ram_used_bytes': 51396, 'ram_limit_bytes': 98304, 'flash_used_bytes': 139368, 'flash_limit_bytes': 524288}

## esp32s3 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e71e4-ab8b-70a3-a4f0-b894ceb098bf
- latency_ms: {'mean_ms': 11.72177887788779, 'p50_ms': 11.723, 'p99_ms': 11.727}
- Wh/1000: 0.0014381879511469657
- telemetry: {'grouped_instants': {'bme280': 34, 'ina219': 230}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'ina219': {'current': 230, 'power': 230, 'voltage': 230}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.7998533724340176, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 508384, 'firmware_elf_bytes': 11906348, 'ram_used_bytes': 44268, 'ram_limit_bytes': 327680, 'flash_used_bytes': 508021, 'flash_limit_bytes': 3342336}

## esp32s3 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e71e6-290e-70a0-a30c-fc3b5f797aba
- latency_ms: {'mean_ms': 551.078406779661, 'p50_ms': 551.075, 'p99_ms': 551.20796}
- Wh/1000: 0.06800031952919015
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 229}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 229, 'power': 229, 'voltage': 229}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8983050847457628, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 525760, 'firmware_elf_bytes': 12539132, 'ram_used_bytes': 85232, 'ram_limit_bytes': 327680, 'flash_used_bytes': 525401, 'flash_limit_bytes': 3342336}

## esp32s3 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e71e7-8c70-7521-907f-5825a87931ad
- latency_ms: {'mean_ms': 106.51492666666667, 'p50_ms': 106.51, 'p99_ms': 106.55101}
- Wh/1000: 0.013291713345370366
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 226}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 226, 'power': 226, 'voltage': 226}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.2, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 434384, 'firmware_elf_bytes': 12606968, 'ram_used_bytes': 68848, 'ram_limit_bytes': 327680, 'flash_used_bytes': 434017, 'flash_limit_bytes': 3342336}

## nano33 / ad

- status: fail
- corpus_tag: N3
- footprint: None

## nano33 / ad

- status: fail
- corpus_tag: N3
- footprint: None

## nano33 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e7543-37c3-7e32-bd60-339408178788
- latency_ms: {'mean_ms': 12.41623088863019, 'p50_ms': 12.42, 'p99_ms': 12.448}
- Wh/1000: 6.0082101280558794e-06
- energy_quarantined: true — INA219 current path anomaly; latency remains valid.
- telemetry: {'grouped_instants': {'bme280': 48, 'ina219': 308}, 'rows': {'bme280': {'humidity': 48, 'pressure': 48, 'temperature': 48}, 'ina219': {'current': 308, 'power': 308, 'voltage': 308}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6947679601405105, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 282096, 'firmware_elf_bytes': 426492, 'ram_used_bytes': 69072, 'ram_limit_bytes': 262144, 'flash_used_bytes': 282096, 'flash_limit_bytes': 983040}

## nano33 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e7545-f8a5-75e0-a20d-857ae690429e
- latency_ms: {'mean_ms': 1232.320846153846, 'p50_ms': 1232.3339999999998, 'p99_ms': 1232.92325}
- Wh/1000: 0.0004122049465811967
- energy_quarantined: true — INA219 current path anomaly; latency remains valid.
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 210}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 210, 'power': 210, 'voltage': 210}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8461538461538461, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 280464, 'firmware_elf_bytes': 436696, 'ram_used_bytes': 110032, 'ram_limit_bytes': 262144, 'flash_used_bytes': 280464, 'flash_limit_bytes': 983040}

## nano33 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e7548-0873-7571-99dd-e67e5eb23723
- latency_ms: {'mean_ms': 224.11116083916085, 'p50_ms': 224.122, 'p99_ms': 224.14916}
- Wh/1000: 6.259632867132867e-05
- energy_quarantined: true — INA219 current path anomaly; latency remains valid.
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 207}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 207, 'power': 207, 'voltage': 207}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24475524475524477, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 209560, 'firmware_elf_bytes': 366632, 'ram_used_bytes': 93648, 'ram_limit_bytes': 262144, 'flash_used_bytes': 209560, 'flash_limit_bytes': 983040}

## nano33 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e755c-e759-7ff3-8303-c589cf777493
- latency_ms: {'mean_ms': 224.1243986013986, 'p50_ms': 224.127, 'p99_ms': 224.14974}
- Wh/1000: 6.579763986013984e-05
- energy_quarantined: true — diagnostic FNB58/INA219 cross-check; not A03 repeatability energy.
- telemetry: {'grouped_instants': {'bme280': 33, 'fnb58': 129, 'ina219': 215}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'fnb58': {'current': 129, 'power': 129, 'voltage': 129}, 'ina219': {'current': 215, 'power': 215, 'voltage': 215}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24475524475524477, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 209560, 'firmware_elf_bytes': 366632, 'ram_used_bytes': 93648, 'ram_limit_bytes': 262144, 'flash_used_bytes': 209560, 'flash_limit_bytes': 983040}

## nano33 / kws

- status: fail
- corpus_tag: N3
- run_id: 019e7564-8561-7cc3-b6fb-9359503a5a88
- latency_ms: {'mean_ms': 224.11586713286712, 'p50_ms': 224.129, 'p99_ms': 224.15547999999998}
- Wh/1000: 0.0023539612665112648
- energy_quarantined: true - diagnostic fixed-path FNB58/INA219 smoke run; not A03 repeatability energy.
- telemetry: {'grouped_instants': {'bme280': 33, 'fnb58': 129, 'ina219': 210}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'fnb58': {'current': 129, 'power': 129, 'voltage': 129}, 'ina219': {'current': 210, 'power': 210, 'voltage': 210}}, 'partial': True, 'partial_sources': ['ina219']}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24475524475524477, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 209560, 'firmware_elf_bytes': 366632, 'ram_used_bytes': 93648, 'ram_limit_bytes': 262144, 'flash_used_bytes': 209560, 'flash_limit_bytes': 983040}

## nano33 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e7567-3aea-7621-9671-32874cf4529e
- latency_ms: {'mean_ms': 12.415842840512223, 'p50_ms': 12.404, 'p99_ms': 12.448}
- Wh/1000: 0.00018829134706592528
- telemetry: {'grouped_instants': {'bme280': 48, 'ina219': 313}, 'rows': {'bme280': {'humidity': 48, 'pressure': 48, 'temperature': 48}, 'ina219': {'current': 313, 'power': 313, 'voltage': 313}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6947679601405105, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 282096, 'firmware_elf_bytes': 426492, 'ram_used_bytes': 69072, 'ram_limit_bytes': 262144, 'flash_used_bytes': 282096, 'flash_limit_bytes': 983040}

## nano33 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e7569-6922-7123-be2a-5478fcbd3e5f
- latency_ms: {'mean_ms': 1232.5413461538462, 'p50_ms': 1232.594, 'p99_ms': 1233.225}
- Wh/1000: 0.013639584519230766
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 212}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 212, 'power': 212, 'voltage': 212}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8461538461538461, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 280464, 'firmware_elf_bytes': 436696, 'ram_used_bytes': 110032, 'ram_limit_bytes': 262144, 'flash_used_bytes': 280464, 'flash_limit_bytes': 983040}

## nano33 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e756b-3d0c-7610-be25-85b897d45d51
- latency_ms: {'mean_ms': 224.11978321678322, 'p50_ms': 224.13, 'p99_ms': 224.16816}
- Wh/1000: 0.002366554372571872
- telemetry: {'grouped_instants': {'bme280': 33, 'ina219': 217}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'ina219': {'current': 217, 'power': 217, 'voltage': 217}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24475524475524477, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 209560, 'firmware_elf_bytes': 366632, 'ram_used_bytes': 93648, 'ram_limit_bytes': 262144, 'flash_used_bytes': 209560, 'flash_limit_bytes': 983040}

## f401re / ic

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ic

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ic

- status: pass
- corpus_tag: N3
- run_id: 019e7598-6637-7dd0-974b-881675b0bedc
- latency_ms: {'mean_ms': 755.4177311827957, 'p50_ms': 755.411, 'p99_ms': 755.50456}
- Wh/1000: 0.07136006152927117
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 280, 'ina219': 469}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 280, 'power': 280, 'voltage': 280}, 'ina219': {'current': 469, 'power': 469, 'voltage': 469}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8279569892473119, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 206948, 'firmware_elf_bytes': 274280, 'ram_used_bytes': 67780, 'ram_limit_bytes': 98304, 'flash_used_bytes': 206480, 'flash_limit_bytes': 524288}

## f401re / ic

- status: pass
- corpus_tag: N3
- run_id: 019e759a-52b9-71e0-8769-486b450e2244
- latency_ms: {'mean_ms': 755.4199462365591, 'p50_ms': 755.423, 'p99_ms': 755.51332}
- Wh/1000: 0.07102978126344078
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 280, 'ina219': 465}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 280, 'power': 280, 'voltage': 280}, 'ina219': {'current': 465, 'power': 465, 'voltage': 465}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8279569892473119, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 206948, 'firmware_elf_bytes': 274280, 'ram_used_bytes': 67780, 'ram_limit_bytes': 98304, 'flash_used_bytes': 206480, 'flash_limit_bytes': 524288}

## f401re / ic

- status: pass
- corpus_tag: N3
- run_id: 019e75fe-9c3b-7061-9423-2831fac5798d
- latency_ms: {'mean_ms': 755.4178709677419, 'p50_ms': 755.418, 'p99_ms': 755.49216}
- Wh/1000: 0.0715778420430108
- telemetry: {'grouped_instants': {'bme280': 71, 'fnb58': 281, 'ina219': 480}, 'rows': {'bme280': {'humidity': 71, 'pressure': 71, 'temperature': 71}, 'fnb58': {'current': 281, 'power': 281, 'voltage': 281}, 'ina219': {'current': 480, 'power': 480, 'voltage': 480}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8279569892473119, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 206948, 'firmware_elf_bytes': 274280, 'ram_used_bytes': 67780, 'ram_limit_bytes': 98304, 'flash_used_bytes': 206480, 'flash_limit_bytes': 524288}

## f401re / kws

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / ad

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / kws

- status: pass
- corpus_tag: N3
- run_id: 019f366f-357b-7820-b347-949b9832f1e8
- latency_ms: {'mean_ms': 158.9308910891089, 'p50_ms': 158.923, 'p99_ms': 158.98199}
- Wh/1000: 0.0215370029909241
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 134, 'ina219': 229}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 134, 'power': 134, 'voltage': 134}, 'ina219': {'current': 229, 'power': 229, 'voltage': 229}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24257425742574257, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 136300, 'firmware_elf_bytes': 205180, 'ram_used_bytes': 51612, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135836, 'flash_limit_bytes': 524288}

## f401re / ad

- status: fail
- corpus_tag: N3
- run_id: 019f3675-53cc-7a92-860a-f0e60f02f711
- latency_ms: {'mean_ms': 8.137413170607678, 'p50_ms': 8.136, 'p99_ms': 8.181}
- Wh/1000: 0.001297974827739638
- telemetry: {'grouped_instants': {'bme280': 48, 'fnb58': 191, 'ina219': 317}, 'rows': {'bme280': {'humidity': 48, 'pressure': 48, 'temperature': 48}, 'fnb58': {'current': 191, 'power': 191, 'voltage': 191}, 'ina219': {'current': 317, 'power': 317, 'voltage': 317}}, 'partial': True, 'partial_sources': ['ina219']}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6946563878770827, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 210396, 'firmware_elf_bytes': 266924, 'ram_used_bytes': 27180, 'ram_limit_bytes': 98304, 'flash_used_bytes': 209928, 'flash_limit_bytes': 524288}

## f401re / ad

- status: pass
- corpus_tag: N3
- run_id: 019f3676-d96e-7f10-9907-3586f4f15606
- latency_ms: {'mean_ms': 8.137278031456114, 'p50_ms': 8.136, 'p99_ms': 8.181}
- Wh/1000: 0.0012900795873499074
- telemetry: {'grouped_instants': {'bme280': 48, 'fnb58': 191, 'ina219': 315}, 'rows': {'bme280': {'humidity': 48, 'pressure': 48, 'temperature': 48}, 'fnb58': {'current': 191, 'power': 191, 'voltage': 191}, 'ina219': {'current': 315, 'power': 315, 'voltage': 315}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6944443800917464, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 210396, 'firmware_elf_bytes': 266924, 'ram_used_bytes': 27180, 'ram_limit_bytes': 98304, 'flash_used_bytes': 209928, 'flash_limit_bytes': 524288}

## f401re / kws

- status: fail
- corpus_tag: N3
- footprint: None

## f401re / kws

- status: fail
- corpus_tag: N3
- run_id: 019f3d83-32b9-74d0-b483-b8f81725204e
- latency_ms: {'mean_ms': 158.93073267326733, 'p50_ms': 158.925, 'p99_ms': 158.986}
- Wh/1000: 0.021390907227722765
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 135, 'ina219': 223}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 135, 'power': 135, 'voltage': 135}, 'ina219': {'current': 223, 'power': 223, 'voltage': 223}}, 'partial': True, 'partial_sources': ['ina219']}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24257425742574257, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 136300, 'firmware_elf_bytes': 205180, 'ram_used_bytes': 51612, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135836, 'flash_limit_bytes': 524288}

## f401re / kws

- status: fail
- corpus_tag: N3
- run_id: 019f3d84-ab01-7533-b0f0-d96b93e2a480
- latency_ms: {'mean_ms': 158.9315297029703, 'p50_ms': 158.9275, 'p99_ms': 158.98399}
- Wh/1000: 0.02114079490511551
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 134, 'ina219': 220}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 134, 'power': 134, 'voltage': 134}, 'ina219': {'current': 220, 'power': 220, 'voltage': 220}}, 'partial': True, 'partial_sources': ['ina219']}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24257425742574257, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 136300, 'firmware_elf_bytes': 205180, 'ram_used_bytes': 51612, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135836, 'flash_limit_bytes': 524288}

## f401re / kws

- status: fail
- corpus_tag: N3
- run_id: 019f3d86-cc72-7831-bac5-f89d8aa87442
- latency_ms: {'mean_ms': 158.93193069306932, 'p50_ms': 158.92849999999999, 'p99_ms': 158.98399}
- Wh/1000: 0.021427479062156217
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 134, 'ina219': 223}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 134, 'power': 134, 'voltage': 134}, 'ina219': {'current': 223, 'power': 223, 'voltage': 223}}, 'partial': True, 'partial_sources': ['ina219']}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24257425742574257, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 136300, 'firmware_elf_bytes': 205180, 'ram_used_bytes': 51612, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135836, 'flash_limit_bytes': 524288}

## f401re / kws

- status: fail
- corpus_tag: N3
- run_id: 019f3d88-5d8a-75d1-b212-6cf0e48e0efb
- latency_ms: {'mean_ms': 158.9315594059406, 'p50_ms': 158.925, 'p99_ms': 158.98399}
- Wh/1000: 0.02138710189218921
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 134, 'ina219': 224}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 134, 'power': 134, 'voltage': 134}, 'ina219': {'current': 224, 'power': 224, 'voltage': 224}}, 'partial': True, 'partial_sources': ['ina219']}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24257425742574257, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 136300, 'firmware_elf_bytes': 205180, 'ram_used_bytes': 51612, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135836, 'flash_limit_bytes': 524288}

## f401re / kws

- status: pass
- corpus_tag: N3
- run_id: 019f3d8a-7a6e-7f92-81de-8e9e49eb795a
- latency_ms: {'mean_ms': 158.93202475247526, 'p50_ms': 158.926, 'p99_ms': 158.98698}
- Wh/1000: 0.02138173289191419
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 134, 'ina219': 223}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 134, 'power': 134, 'voltage': 134}, 'ina219': {'current': 223, 'power': 223, 'voltage': 223}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24257425742574257, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 136300, 'firmware_elf_bytes': 205180, 'ram_used_bytes': 51612, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135836, 'flash_limit_bytes': 524288}

## f401re / ad

- status: pass
- corpus_tag: N3
- run_id: 019f3d8d-b3fd-79b2-885f-007399c54367
- latency_ms: {'mean_ms': 8.137197565305605, 'p50_ms': 8.136, 'p99_ms': 8.181}
- Wh/1000: 0.0013155104190971352
- telemetry: {'grouped_instants': {'bme280': 48, 'fnb58': 192, 'ina219': 315}, 'rows': {'bme280': {'humidity': 48, 'pressure': 48, 'temperature': 48}, 'fnb58': {'current': 192, 'power': 192, 'voltage': 192}, 'ina219': {'current': 315, 'power': 315, 'voltage': 315}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6945149392355483, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 210396, 'firmware_elf_bytes': 266924, 'ram_used_bytes': 27180, 'ram_limit_bytes': 98304, 'flash_used_bytes': 209928, 'flash_limit_bytes': 524288}

## f401re / kws

- status: pass
- corpus_tag: N3
- run_id: 019f43e6-85da-76c2-a654-e834f3f159a7
- latency_ms: {'mean_ms': 158.93173267326733, 'p50_ms': 158.9275, 'p99_ms': 158.985}
- Wh/1000: 0.02111807960808581
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 135, 'ina219': 222}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 135, 'power': 135, 'voltage': 135}, 'ina219': {'current': 222, 'power': 222, 'voltage': 222}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.24257425742574257, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 136300, 'firmware_elf_bytes': 205180, 'ram_used_bytes': 51612, 'ram_limit_bytes': 98304, 'flash_used_bytes': 135836, 'flash_limit_bytes': 524288}

## f401re / ad

- status: pass
- corpus_tag: N3
- run_id: 019f43ea-02f5-7ac0-a2c0-e4fd615f9b08
- latency_ms: {'mean_ms': 8.137214303829571, 'p50_ms': 8.136, 'p99_ms': 8.181}
- Wh/1000: 0.0012954467852312104
- telemetry: {'grouped_instants': {'bme280': 48, 'fnb58': 192, 'ina219': 316}, 'rows': {'bme280': {'humidity': 48, 'pressure': 48, 'temperature': 48}, 'fnb58': {'current': 192, 'power': 192, 'voltage': 192}, 'ina219': {'current': 316, 'power': 316, 'voltage': 316}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6945149392355483, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 210396, 'firmware_elf_bytes': 266924, 'ram_used_bytes': 27180, 'ram_limit_bytes': 98304, 'flash_used_bytes': 209928, 'flash_limit_bytes': 524288}
