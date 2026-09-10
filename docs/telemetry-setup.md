# Telemetry Setup

This guide walks through the physical and software setup for the real telemetry
sources signal-bench captures during Phase 5 measurement. Mocks
(`MockINA219Source`, `MockBME280Source`) remain the default for CI and
no-hardware smoke tests. Set `SIGNAL_BENCH_REAL_I2C=1` or
`SIGNAL_BENCH_REAL_TELEMETRY=1` to replace those mocks with the real
MCP2221A/Blinka-backed I2C sources.

The guide is staged. Each stage adds one class of source to the running
roster.

## Stage 1: FNB58 wall-side meter

The FNB58 source supports two transports:

- `FNB58_TRANSPORT=ble`: BLE fallback, using `FNB58_ADDRESS`.
- `FNB58_TRANSPORT=usb_hid`: USB-HID over the meter's micro-USB PC/data port.

BLE remains the default until the USB-HID gates are passed on the bench. Once
USB-HID is trusted for this unit, set `FNB58_TRANSPORT=usb_hid` for wall-side
cross-check captures. The source tag remains `fnb58` for both transports.

### BLE fallback

`FnirsiSource` connects to the FNIRSI FNB58 Bluetooth variant through `bleak`.
The meter does not need to appear in the macOS Bluetooth device list; on macOS,
CoreBluetooth exposes it to `bleak` as a UUID. A power-off / power-on scan is the
most reliable way to confirm the discovered `FNB58-*` advertisement belongs to
the physical unit on the bench.

Checklist:

1. Power the meter and leave it on the live voltage/current/power screen.
2. Force-quit the FNIRSI mobile companion app, if installed, so it does not hold the exclusive
   BLE connection.
3. Scan without a friendly-name filter; match the meter by BLE address or
   service/characteristic UUID. On macOS the address is a CoreBluetooth UUID,
   not a MAC address.
4. Export the address:

```bash
export FNB58_ADDRESS="<ble-address>"
```

The source writes to `0000ffe9-0000-1000-8000-00805f9b34fb` and subscribes to
`0000ffe4-0000-1000-8000-00805f9b34fb`. Live captures from a discovered FNB58
notifications at roughly 10 Hz, but voltage/current/power measurements arrive
as framed type-`0x04` payloads at roughly 4 Hz. The decoder scans each
notification for `aa type len payload checksum` frames, decodes the 12-byte
type-`0x04` measurement payload as little-endian signed 32-bit voltage/current
fields scaled by 10000, and derives power as `voltage * current`. Well-formed
status frames are ignored.

Known P0 validation point, 2026-05-21: the bench meter advertised at
CoreBluetooth UUID `<your discovered FNB58 address>`; a clean 30 s
telemetry run produced 120 grouped voltage/current/power samples over 33.80 s
with `telemetry_partial=false`.

### USB-HID transport

`FnirsiHidSource` reads the FNB58's HID interface through Python `hidapi`. It
searches the known reverse-engineered FNB58 USB IDs, including
`0x2e3c:0x5558` from `baryluk/fnirsi-usb-power-data-logger` and
`0x0716:0x5030/0x5031` from the macOS prior-art app. The parser expects one
64-byte data packet to carry four 15-byte measurement sub-samples. It decodes
voltage/current, derives power as `voltage * current`, and emits all four
sub-samples as grouped `TelemetrySample` rows tagged `fnb58`.

Enable USB-HID explicitly:

```bash
export FNB58_TRANSPORT=usb_hid
uv run signal-bench telemetry test --duration 30 --output json
```

If macOS HID access fails, keep using BLE:

```bash
export FNB58_TRANSPORT=ble
export FNB58_ADDRESS="<ble-address>"
```

Gate U-2 acceptance for USB-HID is a clean 30 s capture at roughly 100 grouped
samples/s with `telemetry_partial=false`. Gate U-3 additionally compares INA219
rail-side power before and after the micro-USB data cable is attached; the rail
reading must not shift beyond measurement noise.

## Stage 2: I2C sensors via MCP2221A

### What this stage adds

Stage 2 replaces `MockINA219Source` and `MockBME280Source` with real I2C
breakouts on a single USB-to-I2C bridge. The bridge is an Adafruit MCP2221A.
The sensors are an Adafruit INA219 current/voltage monitor and an Adafruit
BME280 environmental sensor. The data path is a STEMMA QT chain; the measured
power path is the positive supply rail routed through the INA219 shunt.

The MCP2221A is a Microchip USB 2.0-to-I2C/UART protocol converter. Adafruit's
desktop Python path uses `hidapi` plus Blinka and requires
`BLINKA_MCP2221=1`. The INA219 STEMMA QT breakout uses default I2C address
`0x40`. The Adafruit BME280 breakout defaults to `0x77`; soldering its address
jumper or tying `SDO` to ground changes it to `0x76`.

Sources:

- Adafruit MCP2221 guide:
  `https://learn.adafruit.com/circuitpython-libraries-on-any-computer-with-mcp2221`
- Microchip MCP2221A product page:
  `https://www.microchip.com/en-us/product/mcp2221a`
- Adafruit INA219 guide:
  `https://learn.adafruit.com/adafruit-ina219-current-sensor-breakout`
- Adafruit BME280 guide:
  `https://cdn-learn.adafruit.com/downloads/pdf/adafruit-bme280-humidity-barometric-pressure-temperature-sensor-breakout.pdf`

### Hardware bill of materials

| Item | Source | Notes |
|---|---|---|
| Adafruit MCP2221A breakout | Adafruit product 4471 | USB-to-I2C bridge with STEMMA QT |
| Adafruit INA219 current sensor breakout | Adafruit product 4226 | STEMMA QT, default address `0x40` |
| Adafruit BME280 environmental sensor | Adafruit product 2652 | STEMMA QT, default address `0x77` |
| STEMMA QT cables | Adafruit product 4399 or equivalent | Two cables minimum |
| Host USB data cable | Any known-good data cable | Connects host to MCP2221A |
| DUT power wiring | Bench-specific | Routes positive supply through INA219 `VIN+` / `VIN-` |

The launch-tier lab rig uses Adafruit MCP2221A, Adafruit INA219, and Adafruit
BME280 breakouts connected over STEMMA QT.

### MCP2221A driver setup

Use a virtual environment or `uv` environment for the Python packages. The repo
already declares the CircuitPython libraries used by the real sources; the
commands below are the direct driver smoke path for a fresh host.

#### macOS primary path

Adafruit's current MCP2221 macOS guide installs `hidapi`, installs Blinka, then
sets `BLINKA_MCP2221`.

```bash
python3 --version
python3 -m pip install hidapi adafruit-blinka
export BLINKA_MCP2221="1"
echo "$BLINKA_MCP2221"
```

Confirm Blinka sees the MCP2221 pin map:

```bash
uv run python - <<'PY'
import board

print("SCL:", board.SCL)
print("SDA:", board.SDA)
PY
```

On the measured Mac this prints MCP2221A-backed Blinka pin objects for `SCL`
and `SDA`; exact object repr text can vary by Blinka release.

Confirm the USB device is visible to macOS:

```bash
system_profiler SPUSBDataType | grep -i -A6 'mcp\\|microchip'
```

On macOS the MCP2221A appears in `system_profiler SPUSBDataType` as a Microchip
USB device.

#### Linux secondary path

Adafruit's Linux setup installs `libusb` and `libudev`, removes or blacklists
the kernel `hid_mcp2221` driver when it captures the device, installs Blinka,
and sets `BLINKA_MCP2221`.

```bash
sudo apt-get update
sudo apt-get install -y libusb-1.0 libudev-dev python3-pip
python3 -m pip install hidapi adafruit-blinka
export BLINKA_MCP2221=1
```

If Python cannot open the device and `lsmod | grep hid_mcp2221` shows the
native kernel module loaded, blacklist it:

```bash
echo 'blacklist hid_mcp2221' | sudo tee /etc/modprobe.d/blacklist-mcp2221.conf
sudo update-initramfs -u
sudo reboot
```

Do not blacklist `hid_mcp2221` unless the native driver blocks Blinka access on
the reproducing host.

Verify USB enumeration:

```bash
lsusb | grep -i -E '04d8:00dd|microchip|mcp2221'
```

Linux descriptor strings vary by distribution and kernel; the VID/PID or
Microchip/MCP2221 text is the stable check.

### STEMMA QT data wiring

The STEMMA QT cable carries SDA, SCL, 3.3 V, and ground. It is only the I2C
data/control bus; it is not the device-under-test power path.

```text
Host USB port
  -> MCP2221A USB-I2C bridge
  -> STEMMA QT cable
  -> INA219 STEMMA QT connector
  -> STEMMA QT cable
  -> BME280 STEMMA QT connector
```

1. Plug the MCP2221A into the host with a known-good USB data cable.
2. Connect MCP2221A `STEMMA QT` to one INA219 `STEMMA QT` connector.
3. Connect the other INA219 `STEMMA QT` connector to the BME280 `STEMMA QT`
   connector.
4. Leave the BME280 at the end of the chain unless another I2C device is added.

The launch-tier INA219 board has STEMMA QT in and out connectors populated; use
the second connector to chain BME280.

### INA219 measurement wiring

The INA219 shunt goes in series with the positive supply path for the target
board. It is a high-side measurement in the normal signal-bench rig.

```text
5 V supply positive
  -> INA219 VIN+
  -> INA219 shunt
  -> INA219 VIN-
  -> DUT positive input

Supply ground
  -> DUT ground
```

Rules:

1. Put `VIN+` on the supply side.
2. Put `VIN-` on the load/DUT side.
3. Keep the supply ground and DUT ground common.
4. Do not route target load current through the STEMMA QT cable.
5. If current reads negative, the shunt direction is reversed.

Per-board load-side targets are recorded in `docs/hardware/ina219_wiring.md`
and the board-specific reproduction guides under `docs/hardware/`.

### BME280 wiring and address

The BME280 uses the STEMMA QT data chain above. No separate power wiring is
needed when STEMMA QT is connected. The expected default address is `0x77`.
If the scan reports `0x76`, configure `BME280_ADDRESS=0x76` instead of moving
wires.

The launch-tier BME280 default is `0x77`. If a reproducer's scan reports
`0x76`, pass `--bme280-address 0x76` to the reproduction runner.

### I2C address verification

Run the scan from the same shell where `BLINKA_MCP2221` is set:

```bash
export BLINKA_MCP2221=1
uv run python - <<'PY'
import board
import busio

i2c = busio.I2C(board.SCL, board.SDA)
while not i2c.try_lock():
    pass
try:
    print([hex(address) for address in i2c.scan()])
finally:
    i2c.unlock()
PY
```

Expected output for the default bench:

```text
['0x40', '0x77']
```

Acceptable alternate output if the BME280 address jumper is changed:

```text
['0x40', '0x76']
```

The launch-tier expected scan is `['0x40', '0x77']`, or `['0x40', '0x76']`
when the BME280 address is changed.

Some BME280 breakouts respond at `0x76` instead. If the scan shows `0x76`, set
`BME280_ADDRESS=0x76` before running signal-bench.

If only one address shows, jump to Troubleshooting. If the scan times out
entirely, the MCP2221A driver didn't initialize correctly — back up to the
previous section.

### Configuring signal-bench

Real I2C source selection:

```bash
export BLINKA_MCP2221=1
export SIGNAL_BENCH_REAL_I2C=1
export INA219_ADDRESS=0x40
export BME280_ADDRESS=0x77  # use 0x76 if the scan shows that address
```

Then run:

```bash
uv run signal-bench telemetry test --duration 30 --no-fnb58
```

Expected Gate 1 I2C sample floors over 30 seconds:

- `ina219`: at least 180 grouped samples, 540 scalar rows.
- `bme280`: at least 30 grouped samples, 90 scalar rows.

These floors are intentionally below the configured 8 Hz / 1 Hz rates to allow
USB-I2C scheduler jitter.

If the FNB58 is paired, omit `--no-fnb58` and provide `FNB58_ADDRESS` or
`--fnb58-address`.

### First measurement

Without `SIGNAL_BENCH_REAL_I2C=1`, this exercises the mocks. With that variable
set, it exercises the real INA219/BME280 chain.

```bash
uv run signal-bench telemetry test --duration 5
```

Expected output (the existing T7.5 mock smoke; sample counts are
implementation-dependent and approximate):

```
Run completed
  duration:           5.0 s
  samples_written:    255
  rows_written:       255
  sources:            mock_ina219_main, mock_bme280_lab
```

For the real 30-second gate, use the floor values above rather than the
5-second illustrative mock counts.

The orchestrator emits `run_started`, per-source `source_started`, and
`run_completed` events as JSON lines on stderr — see AD-04 for the event
catalog and `docs/telemetry/observability.md` for filtering recipes.

### Troubleshooting

**USB device not enumerating.**
`lsusb` (Linux) or `system_profiler` (macOS) shows nothing matching MCP2221.
First check the cable — many USB-C cables are charge-only. Try a known-good
data cable. If the chip enumerates briefly then disappears, the host's USB
port may not be supplying the 100 mA the chain draws — try a powered hub.

**I2C scan finds nothing.**
The driver opened the MCP2221A but no sensors responded. Most common cause:
the STEMMA QT cable between MCP2221A and INA219 is unseated — the
plugs click but the latch isn't engaged. Push until you hear the second
click. Less common: a damaged cable. STEMMA QT cables are cheap; keep spares.

**I2C scan finds one sensor, not both.**
The chained sensor is at a duplicate address (e.g. both sensors are BME280
breakouts with the address jumper left at the same address, so they collide), or the
cable between the two sensors is bad. Move the second sensor to a fresh
cable. If the chain still finds only one, check the second sensor's address
jumper. The Adafruit BME280 default is `0x77`; closing the address jumper or
tying `SDO` to ground changes it to `0x76`.

**INA219 reports impossibly large or negative current.**
The measurement-side wiring is backwards: `Vin+` is on the DUT side and
`Vin-` is on the supply side. Swap them. Current direction is signed; the
sign tells you which way you wired it. Voltage will read normally either
way, which is why the wiring error is easy to miss without watching
current sign.

**BME280 reports stuck or stale values.**
Either the sensor sees an address conflict (you're reading from a different
chip than you think — re-run the bus scan) or the breakout has the address
jumper bridged so it's responding at 0x77 while the driver queries 0x76.
Both produce the same symptom (no response or stale data). Re-run the I2C
scan and confirm exactly two distinct addresses are visible.

If BME280 data disappears during a run, the orchestrator marks telemetry
partial when coverage falls below threshold. Treat that run as a wiring or
sensor-health failure, not as a publishable energy measurement.
