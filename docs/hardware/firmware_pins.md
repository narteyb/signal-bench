# Firmware Pins

This file records the firmware source state used for the Post 1 canonical MCU
accuracy evaluation. The streamed `EVAL` firmware was generated and flashed from
the signal-bench repository. The pre-public history rewrite changed commit
identifiers, so this file records reproducible build inputs rather than a
historical commit SHA.

Those build inputs produced the A01 full-eval artifacts under
`data/full-eval/a01/`.
The generated PlatformIO projects were emitted by the repo tooling; generated
build outputs and `.pio` directories are not checked in.

## Common Settings

| Field | Value |
|---|---|
| Protocol | `EVAL <task> <sample_index> <base64-int8-input>` |
| PlatformIO Core | `6.1.19` |
| Firmware version flag | `-DSIGNAL_BENCH_VERSION=\"0.2.0.dev0\"` |
| TFLM library | `spaziochirale/Chirale_TensorFLowLite@2.0.0` |

## Target Pins

| Target | Source state | PlatformIO environment | Platform / framework | Build flags |
|---|---|---|---|---|
| ESP32-S3 | Public tree plus pinned build inputs in this row | `esp32-s3-devkitc-1` | `espressif32@6.6.0` / Arduino | `-w -DSIGNAL_BENCH_VERSION=\"0.2.0.dev0\"` |
| Nano 33 BLE Sense Rev2 | Public tree plus pinned build inputs in this row | `nano33ble` | `nordicnrf52@10.11.0` / Arduino | `-w -Wno-cpp -DSIGNAL_BENCH_VERSION=\"0.2.0.dev0\"` |
| NUCLEO-F401RE | Public tree plus pinned build inputs in this row | `nucleo_f401re` | `ststm32@19.6.0` / Arduino | `build_unflags=-std=gnu++11 -std=gnu++14`; `build_flags=-w -std=gnu++17 -DSIGNAL_BENCH_VERSION=\"0.2.0.dev0\"`; `lib_compat_mode=off` |

The NUCLEO-F401RE A01 firmware used the board's STLink virtual COM port
(`Serial`) for the streamed protocol.
