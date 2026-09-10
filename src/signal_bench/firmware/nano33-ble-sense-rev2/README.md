# Nano 33 BLE Sense Rev2 Firmware

PlatformIO project targeting the **Arduino Nano 33 BLE Sense Rev2** via the
Nano 33 BLE board definition. T1.7 scaffold: native USB-CDC serial,
canned task output, no BLE advertising/scanning, and no sensor initialization.
Phase 1 hardware bring-up replaces the stub with the TinyML wake-word task.
The wire protocol is specified in
[`docs/usb-serial-protocol.md`](../../../../docs/usb-serial-protocol.md).

## Build

From the repo root:

```sh
pio run -d src/signal_bench/firmware/nano33-ble-sense-rev2 -e nano33ble
```

The first build installs the Nordic nRF52 PlatformIO platform, the Arduino Mbed
framework, and the ARM GCC toolchain. On the T1.7 Mac, PlatformIO's primary
package mirror produced transient SSL errors and successfully fell back to
another mirror.

Artifacts land in `.pio/build/nano33ble/`:

- `firmware.bin` - flashable image
- `firmware.elf` - symbols and debug info

## Flash

This scaffold is not the Post 1 launch-tier reproduction firmware. For Post 1
KWS/IC/AD reproduction, use `src/signal_bench/firmware/launch-tier/`.

To flash this scaffold:

```sh
pio run -d src/signal_bench/firmware/nano33-ble-sense-rev2 -e nano33ble -t upload
```

PlatformIO should auto-detect the board's USB-CDC port. If detection fails, pass
`--upload-port <discovered-port>` explicitly.

## Monitor

```sh
pio device monitor -d src/signal_bench/firmware/nano33-ble-sense-rev2 -e nano33ble
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
| platform-nordicnrf52 | 10.11.0 |
| Arduino Mbed framework | `framework-arduino-mbed` 4.5.0 |
| ARM GCC toolchain | `toolchain-gccarmnoneeabi` 1.70201.0 (7.2.1) |
| Python (PlatformIO host) | 3.12 |
| Mac host | Apple Silicon macOS |

## Build Verification

Last verified local build: 2026-05-08.

```text
RAM:   [==        ]  16.2% (used 42464 bytes from 262144 bytes)
Flash: [=         ]   8.1% (used 79180 bytes from 983040 bytes)
```

Artifacts:

- `firmware.bin`: 79180 bytes (78 KB)
- `firmware.elf`: 183676 bytes (180 KB)

The build uses `-Wno-cpp` to suppress a stock Arduino Mbed package `#warning`
about the Nordic LF clock source. The board package already selects the XTAL
source in its generated `mbed_config.h`; attempts to override the setting via a
macro caused redefinition warnings or Mbed link failures.

PlatformIO package cache after the first Nano build: 3.5 GB at `~/.platformio`.

## Notes for Phase 1

The scaffold intentionally does not initialize BLE or on-board sensors. During
hardware bring-up, verify that the board is not advertising BLE before baseline
INA219 measurements, then verify `RUN -> RESULT* -> DONE` against
`MCUAdapterBase`.
