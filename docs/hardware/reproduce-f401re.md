# Reproduce F401RE Launch-Tier Cell

Board: ST NUCLEO-F401RE.

This is the cold-start path from an unwired DUT bench to one F401RE KWS
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

## 2. Wire F401RE

Power boundary:

- FNB58/supply positive -> INA219 `VIN+`
- INA219 `VIN-` -> NUCLEO external 5 V rail (`E5V` / equivalent)
- Common ground between supply, NUCLEO, INA219, and MCP2221A
- JP5 set to `E5V`
- ST-LINK USB attached and enumerated for the virtual COM port
- Board power supplied through the metered E5V path

If ST-LINK USB powers any board section outside the metered path, the run is a
different boundary and is not comparable to the launch-tier acceptance band.
The F401RE devkit boundary includes debug-interface state.

After wiring, rerun discovery:

```bash
uv run python scripts/discover_launch_tier_devices.py --skip-ble
```

Expected F401RE checkpoint:

- A ST-LINK serial port appears, normally an Arduino modem-style path on macOS.
- Healthy ST-LINK identity includes `VID:PID=0483:374B` and description
  `STM32 STLink`.

Set the port:

```bash
export F401RE_PORT="<F401RE ST-LINK serial port from discovery>"
```

## 3. Build

```bash
pio run -d src/signal_bench/firmware/launch-tier/f401re-kws -e nucleo_f401re
```

## 4. Run

Before starting, read the supply setpoint and the FNB58 face. Record what the
screen shows, not what the telemetry stream later reports.

```bash
uv run python scripts/run_launch_tier_cell.py \
  --target f401re \
  --task kws \
  --serial-port "$F401RE_PORT" \
  --fnb58-address "$FNB58_ADDRESS" \
  --power-connector "E5V through metered 5 V rail" \
  --usb-routing "ST-LINK USB attached for VCP; board power supplied by metered E5V" \
  --debug-state "ST-LINK attached and enumerated" \
  --jp5-position "E5V" \
  --physical-routing-verified \
  --supply-setpoint-v "<supply setpoint volts>" \
  --fnb58-face-voltage-v "<FNB58 screen volts>" \
  --fnb58-face-current-a "<FNB58 screen amps>" \
  --fnb58-face-power-w "<FNB58 screen watts>"
```

Expected KWS reproduction band:

- Energy: `18.174-24.589 mWh/1000`
- Latency: `135.087-182.765 ms`

The runner records serial identity, boundary metadata, toolchain versions, host
environment, JP5 state, and the operator-entered supply/FNB58 face readings in
the JSON run record.

## F401RE Troubleshooting

Observed failure mode: the meter rig scans correctly at `0x40` and `0x77`, but
the ST-LINK is absent from both `uv run python scripts/discover_launch_tier_devices.py`
and macOS USB inventory. In that state the board cannot be flashed or measured;
it is a USB enumeration problem, not an INA219/FNB58 problem.

Recovery steps:

1. Leave the metered E5V path in place.
2. Reseat only the ST-LINK USB cable.
3. Try a known-good data cable and another host port or powered hub.
4. Confirm the ST-LINK connector on the Nucleo is the attached USB path.
5. Rerun discovery and continue only after the healthy signature appears:
   `VID:PID=0483:374B`, description `STM32 STLink`, and a discovered ST-LINK
   serial device on macOS.

If ST-LINK appears but the measured power is far below the F401RE KWS band,
check for a VBUS bypass: some board current may be arriving through ST-LINK USB
instead of through the INA219 shunt. That is a different power boundary.
