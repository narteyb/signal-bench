# ESP32-S3 Telemetry Load Firmware

This firmware is a deterministic load source for P1 telemetry bring-up. It is
meant for the ESP32-S3-DevKitC-1 when the board is powered only through the
measurement rail during capture.

The cycle starts automatically after boot and repeats forever:

```text
10 s idle -> 15 s CPU load -> 10 s release/idle
```

No USB serial trigger is required during capture. USB is used only before the
capture to flash the firmware and optionally verify the serial state markers.

## Build and Flash

```bash
cd src/signal_bench/firmware/esp32-s3-telemetry-load
pio run --target upload --upload-port <discovered-port>
pio device monitor -b 115200 --port <discovered-port>
```

Expected serial markers:

```text
signal-bench esp32-s3 telemetry-load ready
cycle=1 phase=idle seconds=10
cycle=1 phase=load seconds=15
cycle=1 phase=release seconds=10
```

After flashing, disconnect USB, power the board through the measured rail, wait
for boot, and start the telemetry capture. Because the cycle loops, the capture
can begin at any point and still catch an idle/load/release transition.
