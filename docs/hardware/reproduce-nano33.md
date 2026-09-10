# Reproduce Nano 33 Launch-Tier Cell

Board: Arduino Nano 33 BLE Sense Rev2.

This is the cold-start path from an unwired DUT bench to one Nano 33 KWS
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

## 2. Wire Nano 33

Power boundary:

- FNB58/supply positive -> INA219 `VIN+`
- INA219 `VIN-` -> Nano `VIN` / `VUSB` load-side 5 V input
- Common ground between supply, Nano, INA219, and MCP2221A
- Native USB serial attached for the benchmark protocol
- USB VBUS isolated or routed through the same metered 5 V path, with no second
  unmetered VBUS feed

After wiring, rerun discovery:

```bash
uv run python scripts/discover_launch_tier_devices.py --skip-ble
```

Expected Nano checkpoint:

- A Nano serial port appears with `VID:PID=2341:805A` in app state.
- `VID:PID=2341:005A` is the bootloader. It can draw a low rail current but
  does not answer the benchmark protocol and is not a valid measured state.

Set the port:

```bash
export NANO33_PORT="<Nano serial port from discovery>"
```

## 3. Build

```bash
pio run -d src/signal_bench/firmware/launch-tier/nano33-kws -e nano33ble
```

## 4. Run

Before starting, read the supply setpoint and the FNB58 face. Record what the
screen shows, not what the telemetry stream later reports.

```bash
uv run python scripts/run_launch_tier_cell.py \
  --target nano33 \
  --task kws \
  --serial-port "$NANO33_PORT" \
  --fnb58-address "$FNB58_ADDRESS" \
  --power-connector "VIN/VUSB through metered 5 V rail" \
  --usb-routing "native USB data attached for serial protocol; USB VBUS isolated or routed through the same metered 5 V path" \
  --debug-state "native USB serial attached and enumerated" \
  --physical-routing-verified \
  --supply-setpoint-v "<supply setpoint volts>" \
  --fnb58-face-voltage-v "<FNB58 screen volts>" \
  --fnb58-face-current-a "<FNB58 screen amps>" \
  --fnb58-face-power-w "<FNB58 screen watts>"
```

Expected KWS reproduction band:

- Energy: `2.237-3.026 mWh/1000`
- Latency: `190.550-257.804 ms`

The runner records serial identity, boundary metadata, toolchain versions, host
environment, the Nano state preflight, and the operator-entered supply/FNB58
face readings in the JSON run record.

## Nano-Specific Troubleshooting

- If discovery shows `VID:PID=2341:005A`, the board is in bootloader state.
  Restore the app with a clean upload or power-cycle back to app state before
  measuring.
- If upload resets make the serial device disappear, wait for it to return and
  rerun discovery. The runner waits for the requested port, but a missing port
  after that means the board did not return on the same device path.
- Reject any Nano KWS run around `0.008 Wh/1000` / `128 mW` even if latency is
  normal. That high-current app state was observed during execution and is
  outside the launch acceptance band under the same wiring. The runner rejects
  Nano app states above `0.060 W` idle INA219 power before it creates a measured
  run record.
