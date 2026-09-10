# NUCLEO-F401RE Firmware

PlatformIO project targeting the **ST NUCLEO-F401RE** with Arduino-on-STM32.
T1.8 scaffold: ST-Link virtual COM port serial protocol, canned task output, no
radios, and no peripheral initialization beyond serial and the ready LED. Phase
1 hardware bring-up replaces the stub with real TinyML task code. The wire
protocol is specified in
[`docs/usb-serial-protocol.md`](../../../../docs/usb-serial-protocol.md).

## Build

From the repo root:

```sh
pio run -d src/signal_bench/firmware/nucleo-f401re -e nucleo_f401re
```

The first build installs the ST STM32 PlatformIO platform, CMSIS packages,
Arduino-on-STM32, and the ARM GCC toolchain. On the T1.8 Mac, PlatformIO's
primary package mirror produced transient SSL errors and successfully fell back
to another mirror.

Artifacts land in `.pio/build/nucleo_f401re/`:

- `firmware.bin` - flashable image
- `firmware.elf` - symbols and debug info

## Flash

This scaffold is not the Post 1 launch-tier reproduction firmware. For Post 1
KWS/IC/AD reproduction, use `src/signal_bench/firmware/launch-tier/`.

To flash this scaffold:

```sh
pio run -d src/signal_bench/firmware/nucleo-f401re -e nucleo_f401re -t upload
```

PlatformIO should auto-detect the ST-Link programmer. If detection fails, pass
the appropriate upload port/debug probe options explicitly.

## Monitor

```sh
pio device monitor -d src/signal_bench/firmware/nucleo-f401re -e nucleo_f401re
```

The firmware does not emit startup chatter on the protocol stream. Send a `RUN`
frame to exercise the stub:

```text
RUN kws 3
```

Expected response:

```text
RESULT 0 1200 [0.42,0.31,0.27]
RESULT 1 1200 [0.42,0.31,0.27]
RESULT 2 1200 [0.42,0.31,0.27]
DONE 3
```

Malformed `RUN` input emits `ERR EINVAL invalid RUN frame`; unknown commands
emit `ERR EUNKNOWN expected RUN <task_id> <iterations>`. The stub never emits
inference errors; real `EINFER` / `ETIMEOUT` / `EHW` paths land when TinyML
inference is wired in during hardware bring-up.

## Verified-Working Toolchain

Last verified: 2026-05-08.

| Component | Version |
|---|---|
| PlatformIO Core | 6.1.19 |
| platform-ststm32 | 19.6.0 |
| Arduino STM32 framework | `framework-arduinoststm32` 4.21200.0 (2.12.0) |
| CMSIS | `framework-cmsis` 2.60300.0 (6.3.0) |
| CMSIS-DSP | `framework-cmsis-dsp` 1.16.2 |
| ARM GCC toolchain | `toolchain-gccarmnoneeabi` 1.120301.0 (12.3.1) |
| Python (PlatformIO host) | 3.12 |
| Mac host | Apple Silicon macOS |

## Build Verification

Last verified local build: 2026-05-08.

```text
RAM:   [          ]   1.2% (used 1156 bytes from 98304 bytes)
Flash: [          ]   3.3% (used 17452 bytes from 524288 bytes)
```

Artifacts:

- `firmware.bin`: 17900 bytes (18 KB)
- `firmware.elf`: 46864 bytes (46 KB)

PlatformIO package cache after the first F401RE build: 6.9 GB at `~/.platformio`.

## Notes for Phase 1

The STM32F401RE has no built-in radio, so the target is radio-quiet by design.
The scaffold intentionally avoids SPI, I2C, ADC, and external sensor setup.
During hardware bring-up, verify ST-Link VCP enumeration, then verify
`RUN -> RESULT* -> DONE` against `MCUAdapterBase`.

Mbed was tried first because it was the preferred framework for this task, but
PlatformIO's `framework-mbed` build adapter imports Python's removed `imp`
module under Python 3.12. Arduino-on-STM32 avoids that local toolchain blocker,
supports GCC 12.3.1 with `-std=gnu++17`, and preserves the same serial protocol
behavior.
