# ESP32-S3 Wake-Word Firmware

PlatformIO project targeting the **ESP32-S3-DevKitC-1**. T1.6 scaffold: prints
version and chip info over USB-CDC, disables radios for measurement stability,
then implements the v1 USB-serial protocol with a canned task stub. Phase 1
hardware bring-up replaces the stub with the TinyML wake-word task.

## Build

From the repo root:

```sh
pio run -d src/signal_bench/firmware/esp32-s3-wake-word
```

First build downloads the ESP-IDF toolchain into PlatformIO's package cache.
On the M3-prep Mac, the first attempted build spent about 140s downloading
packages before surfacing a project-layout issue; after fixing `src_dir = main`,
the first successful compile took 35s. A clean SDK-config rebuild took 23s.
Subsequent no-op builds are faster.

Artifacts land in `.pio/build/esp32-s3-devkitc-1/`:

- `firmware.bin` - flashable image
- `firmware.elf` - symbols and debug info

## Flash

This scaffold is not the Post 1 launch-tier reproduction firmware. For Post 1
KWS/IC/AD reproduction, use `src/signal_bench/firmware/launch-tier/`.

To flash this scaffold:

```sh
pio run -d src/signal_bench/firmware/esp32-s3-wake-word -t upload
```

PlatformIO auto-detects the dev kit's USB-CDC port. If detection fails, pass
`--upload-port <discovered-port>` explicitly.

## Monitor

```sh
pio device monitor -d src/signal_bench/firmware/esp32-s3-wake-word
```

Expected output on boot:

```text
I (XXX) signal-bench: signal-bench v0.1.0.dev0 - ESP32-S3 firmware skeleton
I (XXX) signal-bench: chip: 2 cores, rev 0, flash 8MB
I (XXX) signal-bench: ready (T1.6 protocol scaffold; canned task stub only)
I (XXX) signal-bench: Bluetooth controller not enabled in sdkconfig
I (XXX) signal-bench: radio disable path completed
I (XXX) signal-bench: USB-serial protocol ready: RUN -> RESULT* -> DONE
```

## Protocol Stub

The firmware implements the device side of
[`docs/usb-serial-protocol.md`](../../../../docs/usb-serial-protocol.md):

```text
host -> device: RUN kws 3
device -> host: RESULT 0 1200 [0.42,0.31,0.27]
device -> host: RESULT 1 1200 [0.42,0.31,0.27]
device -> host: RESULT 2 1200 [0.42,0.31,0.27]
device -> host: DONE 3
```

Malformed `RUN` input emits `ERR EINVAL invalid RUN frame`; unknown commands
emit `ERR EUNKNOWN expected RUN <task_id> <iterations>`. The stub never emits
inference errors; real `EINFER` / `ETIMEOUT` / `EHW` paths land when TinyML
inference is wired in during hardware bring-up.

## Verified-Working Toolchain (2026-05-03)

| Component | Version |
|---|---|
| PlatformIO Core | 6.1.19 |
| platform-espressif32 | 6.6.0 |
| ESP-IDF | 5.2.1 (`framework-espidf` 3.50201.240515) |
| Xtensa toolchain | `toolchain-xtensa-esp32s3` 12.2.0+20230208 |
| Python (PlatformIO host) | 3.12 |
| Mac host | Apple Silicon macOS |

Update this table when bumping any pinned version. Per Architecture R3, version
drift is the dominant build-chain risk.

## Build Verification

Last verified local build: 2026-05-08.

```text
RAM:   [=         ]   7.2% (used 23468 bytes from 327680 bytes)
Flash: [===       ]  29.9% (used 313921 bytes from 1048576 bytes)
```

Artifacts:

- `firmware.bin`: 314288 bytes (307 KB)
- `firmware.elf`: 3809600 bytes (3.6 MB)

PlatformIO package cache after first install: 2.7 GB at `~/.platformio`.

## Notes for M3 Proper

`platform-espressif32` 6.6.0 resolves to ESP-IDF 5.2.1, not 5.1.2. The
framework package is pinned explicitly in `platformio.ini`.

PlatformIO's stock `esp32-s3-devkitc-1` board definition is
`ESP32-S3-DevKitC-1-N8 (8 MB QD, No PSRAM)`. Dan's target board is expected to
be the N8R8 revision. M3 proper should confirm the exact module on arrival and
either add a project-local N8R8 board definition or switch to a compatible
PlatformIO board ID with 8 MB PSRAM enabled.

During the first package install, PlatformIO's primary package mirror produced
transient SSL errors and successfully fell back to another mirror. No code
change was required, but this is worth remembering if fresh machines see slow
first installs.
