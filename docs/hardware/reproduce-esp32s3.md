# Reproduce ESP32-S3 Launch-Tier Cell

Board: ESP32-S3 DevKitC.

This is the cold-start path from an unwired DUT bench to one ESP32-S3 KWS
measurement. Run commands from the repository root after `uv sync --extra dev`.

## 1. Common Rig

1. Disconnect any target board from USB and from the metered load path.
2. Connect the MCP2221A to the host.
3. Chain MCP2221A -> INA219 -> BME280 over STEMMA QT.
4. Set the shell environment:

```bash
export BLINKA_MCP2221=1
export SIGNAL_BENCH_REAL_I2C=1
export FNB58_TRANSPORT=ble
```

5. Discover the meter and I2C chain:

```bash
uv run python scripts/discover_launch_tier_devices.py
```

Expected common-rig checkpoints:

- I2C scan includes `0x40` for INA219 and `0x77` or `0x76` for BME280.
- The FNB58 appears under "FNB58 BLE candidates"; export that address:

```bash
export FNB58_ADDRESS="<your discovered FNB58 address>"
```

## 2. Wire ESP32-S3

Power boundary:

- FNB58/supply positive -> INA219 `VIN+`
- INA219 `VIN-` -> ESP32-S3 board `5V` / `V+` load-side input
- Common ground between supply, ESP32-S3, INA219, and MCP2221A
- Native USB serial attached for the benchmark protocol
- USB VBUS isolated or routed through the same metered 5 V path, with no second
  unmetered VBUS feed

After wiring, rerun discovery:

```bash
uv run python scripts/discover_launch_tier_devices.py --skip-ble
```

Expected ESP32-S3 checkpoint:

- A CP210x/USB-serial port appears. On macOS this is usually a USB-serial
  device path, not an Arduino modem-style path; use the discovered port.

Set the port:

```bash
export ESP32S3_PORT="<ESP32-S3 serial port from discovery>"
```

## 3. Build

```bash
pio run -d src/signal_bench/firmware/launch-tier/esp32s3-kws -e esp32-s3-devkitc-1
```

## 4. Run

Before starting, read the supply setpoint and the FNB58 face. Record what the
screen shows, not what the telemetry stream later reports.

```bash
uv run python scripts/run_launch_tier_cell.py \
  --target esp32s3 \
  --task kws \
  --serial-port "$ESP32S3_PORT" \
  --fnb58-address "$FNB58_ADDRESS" \
  --power-connector "5V/V+ through metered 5 V rail" \
  --usb-routing "native USB data attached for serial protocol; USB VBUS isolated or routed through the same metered 5 V path" \
  --debug-state "native USB serial attached and enumerated" \
  --physical-routing-verified \
  --supply-setpoint-v "<supply setpoint volts>" \
  --fnb58-face-voltage-v "<FNB58 screen volts>" \
  --fnb58-face-current-a "<FNB58 screen amps>" \
  --fnb58-face-power-w "<FNB58 screen watts>"
```

Expected KWS reproduction band:

- Energy: `11.537-15.609 mWh/1000`
- Latency: `90.521-122.470 ms`

The runner records serial identity, boundary metadata, toolchain versions, host
environment, and the operator-entered supply/FNB58 face readings in the JSON run
record.

## ESP32-S3 Troubleshooting

- If no ESP32-S3 serial port appears, check that the USB cable is data-capable
  and that USB VBUS is not unintentionally bypassing the metered power path.
- The expected port may be a USB-serial device path on macOS. Do not assume an
  Arduino modem-style name.
- Hold BOOT/RESET only if normal auto-reset upload fails.
