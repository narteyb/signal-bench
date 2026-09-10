
## esp32s3 / kws

- status: pass
- corpus_tag: N3
- run_id: 019e5d7f-0d12-72f0-b07b-7a384b978c9b
- latency_ms: {'mean_ms': 106.49781, 'p50_ms': 106.496, 'p99_ms': 106.52101}
- Wh/1000: 0.013223984438888874
- telemetry: {'grouped_instants': {'bme280': 33, 'fnb58': 130, 'ina219': 220}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'fnb58': {'current': 130, 'power': 130, 'voltage': 130}, 'ina219': {'current': 220, 'power': 220, 'voltage': 220}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.25, 'documented_metric': 'top1', 'documented_variant': 0.881799591002045, 'documented_retention': 0.6339468302658413}
- footprint: {'firmware_bin_bytes': 430464, 'firmware_elf_bytes': 12602896, 'ram_used_bytes': 68848, 'ram_limit_bytes': 327680, 'flash_used_bytes': 430101, 'flash_limit_bytes': 3342336}

## esp32s3 / ic

- status: pass
- corpus_tag: N3
- run_id: 019e5d80-801f-75a2-a740-2f8d27174cdf
- latency_ms: {'mean_ms': 551.0668474576271, 'p50_ms': 551.06, 'p99_ms': 551.20054}
- Wh/1000: 0.06772580485875701
- telemetry: {'grouped_instants': {'bme280': 33, 'fnb58': 132, 'ina219': 222}, 'rows': {'bme280': {'humidity': 33, 'pressure': 33, 'temperature': 33}, 'fnb58': {'current': 132, 'power': 132, 'voltage': 132}, 'ina219': {'current': 222, 'power': 222, 'voltage': 222}}, 'partial': False, 'partial_sources': []}
- accuracy_proxy: {'metric': 'top1_subset', 'value': 0.8305084745762712, 'documented_metric': 'top1', 'documented_variant': 0.8577, 'documented_retention': -1.419999999999999}
- footprint: {'firmware_bin_bytes': 501200, 'firmware_elf_bytes': 12514580, 'ram_used_bytes': 85232, 'ram_limit_bytes': 327680, 'flash_used_bytes': 500829, 'flash_limit_bytes': 3342336}

## esp32s3 / ad

- status: pass
- corpus_tag: N3
- run_id: 019e5d81-fc94-75c3-aafd-28bba9de0569
- latency_ms: {'mean_ms': 11.72173964063073, 'p50_ms': 11.723, 'p99_ms': 11.727}
- Wh/1000: 0.0014434760671067103
- telemetry: {'grouped_instants': {'bme280': 34, 'fnb58': 133, 'ina219': 225}, 'rows': {'bme280': {'humidity': 34, 'pressure': 34, 'temperature': 34}, 'fnb58': {'current': 133, 'power': 133, 'voltage': 133}, 'ina219': {'current': 225, 'power': 225, 'voltage': 225}}, 'partial': True, 'partial_sources': ['ina219']}
- accuracy_proxy: {'metric': 'auroc_subset', 'value': 0.6946279231383248, 'documented_metric': 'auroc', 'documented_variant': 0.8390887241689129, 'documented_retention': 0.9707224965601617}
- footprint: {'firmware_bin_bytes': 503264, 'firmware_elf_bytes': 11902276, 'ram_used_bytes': 44268, 'ram_limit_bytes': 327680, 'flash_used_bytes': 502905, 'flash_limit_bytes': 3342336}
