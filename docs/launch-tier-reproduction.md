# Launch-Tier MCU Reproduction

This guide is the public path from a clean clone to one measured Post 1 MCU
cell. It covers only the launch tier: NUCLEO-F401RE, Arduino Nano 33 BLE Sense
Rev2, ESP32-S3 DevKitC, FNB58, INA219 over MCP2221A, and BME280. Pi, Hailo,
Jetson, M1 Max, and cloud targets are out of scope here.

## What This Proves

This path verifies that the documented method works on Dan's bench with Dan's
boards and host. It does not prove universal reproduction on every board,
supply, hub, or room. Outside reproduction is expected to be looser; use
`docs/launch-tier-acceptance-bands.md` to decide whether a measurement is
close enough to count as a method reproduction.

## Clean Host Setup

From a clean clone:

```bash
git clone https://github.com/narteyb/signal-bench
cd signal-bench
uv sync --extra dev
```

Install PlatformIO Core 6.1.19, then confirm:

```bash
pio --version
# PlatformIO Core, version 6.1.19
```

The reproduction path is verified against the current pinned PlatformIO
projects in `src/signal_bench/firmware/launch-tier/**/platformio.ini`:

| Board | PlatformIO environment | Pinned platform | Pinned TFLM library |
|---|---|---|---|
| F401RE | `nucleo_f401re` | `ststm32@19.6.0` | `spaziochirale/Chirale_TensorFLowLite@2.0.0` |
| Nano 33 | `nano33ble` | `nordicnrf52@10.11.0` | `spaziochirale/Chirale_TensorFLowLite@2.0.0` |
| ESP32-S3 | `esp32-s3-devkitc-1` | `espressif32@6.6.0` | `spaziochirale/Chirale_TensorFLowLite@2.0.0` |

Limit: the exact toolchain versions used by the original published runs are not
fully attestable from committed history. The versions above are the versions
the reproduction path is pinned to and verified against now; run records capture
the full `pio pkg list` output for each reproduction run.

## Common Rig Discovery

Start from an unwired DUT bench: no Nano 33, ESP32-S3, or F401RE connected to
the load path or USB.

1. Connect the MCP2221A to the host.
2. Chain MCP2221A -> INA219 -> BME280 over STEMMA QT.
3. Power the FNB58 and leave it on the live voltage/current/power screen.
4. Set the project environment:

```bash
export BLINKA_MCP2221=1
export SIGNAL_BENCH_REAL_I2C=1
export FNB58_TRANSPORT=ble
```

5. Discover serial devices, the I2C chain, and FNB58 BLE address:

```bash
uv run python scripts/discover_launch_tier_devices.py
```

Expected launch rig:

- I2C scan is `['0x40', '0x77']`, or `['0x40', '0x76']` if the BME280 address
  jumper is changed. Use `--bme280-address 0x76` in that case.
- The FNB58 appears under "FNB58 BLE candidates". Export the discovered address:

```bash
export FNB58_ADDRESS="<your discovered FNB58 address>"
```

Use `uv run python` for repository Python commands. The project dependencies
installed by `uv sync --extra dev` are not guaranteed to be available to global
`python3`.

## Per-Board Cold-Start Paths

Use the board-specific guide for wiring order, serial discovery, run command,
expected band, and observed failure modes:

- `docs/hardware/reproduce-f401re.md`
- `docs/hardware/reproduce-nano33.md`
- `docs/hardware/reproduce-esp32s3.md`

Each board guide follows the same structure:

1. Start with the common rig verified.
2. Wire one board into the metered 5 V boundary.
3. Rerun discovery and set the board's serial-port environment variable.
4. Build the KWS firmware.
5. Read the supply setpoint and FNB58 face.
6. Run `scripts/run_launch_tier_cell.py`.
7. Compare the JSON run record to `docs/launch-tier-acceptance-bands.md`.

## Run Record Provenance

`scripts/run_launch_tier_cell.py` builds the committed firmware, flashes the
selected board unless `--skip-upload` is passed, runs the target state
preflight, runs a 5-inference probe, measures a 32-second window, captures
INA219/BME280/FNB58 telemetry, and writes a JSON run record under
`results/launch_tier_reproduction/`.

The run record includes:

- Host OS, Python version, and PlatformIO/package output.
- Firmware footprint.
- Serial-port identity, including VID/PID and USB serial number when available.
- Boundary strings, JP5/debug state, and whether the operator verified physical
  routing.
- INA219/BME280/FNB58 telemetry summaries.
- Operator-entered supply setpoint and FNB58 face readings.
- Nano 33 USB/app-state and idle-power preflight when the target is Nano 33.

## Acceptance Bands

Acceptance bands are generated from the launch measurement database and the SR
1.5 rebuilt-rig tolerance floor:

```bash
uv run python scripts/generate_launch_tier_acceptance_bands.py \
  --db data/p3_mcu_matrix.db \
  --output docs/launch-tier-acceptance-bands.md
```

Verify the committed band file matches the database:

```bash
uv run python scripts/generate_launch_tier_acceptance_bands.py \
  --db data/p3_mcu_matrix.db \
  --output docs/launch-tier-acceptance-bands.md \
  --check
```

`data/p3_mcu_matrix.db` is a local working database and is intentionally not
tracked in git. Public no-hardware verification regenerates the same bands from
the pinned Hugging Face telemetry bundle:

```bash
uv run python scripts/verify_post1_from_bundle.py
```

## Troubleshooting

Project Python command fails with `ModuleNotFoundError`:

- Re-run the command as `uv run python ...`; do not use global `python3` for
  repo-provided Python dependencies.

FNB58 address unknown:

- Run `uv run python scripts/discover_launch_tier_devices.py` with the meter
  powered on and the FNIRSI mobile app closed. Export the address shown under
  "FNB58 BLE candidates".

Meters disagree:

- If FNB58 is lower than INA219 by about 4-6%, check the meter-integrity verdict
  before changing published numbers. The repository treats the launch-tier
  FNB58 path as a cross-check, not the authoritative MCU energy source.
- If the two meters disagree by a larger amount, look first for a bypass path:
  USB VBUS, debug USB, or a second supply feeding part of the board outside the
  INA219 shunt. The serial cable may stay attached for the benchmark protocol,
  but its VBUS must be isolated or routed through the same metered 5 V path.

Outside the band:

- Confirm the firmware project and task match the cell.
- Confirm INA219 `VIN+` is supply-side and `VIN-` is board-side.
- Confirm all board current enters through the metered boundary.
- Confirm BME280 ambient is plausible and stable.
- Re-run once after power-cycling the board and FNB58.

Board-specific observed modes:

- Nano 33: app identity is `VID:PID=2341:805A`; bootloader identity is
  `VID:PID=2341:005A`. Bootloader state is not a valid measurement state. A
  high-current responsive app state around `128 mW` was also observed and is
  rejected by the runner's idle-power gate.
- ESP32-S3: the serial port may be a USB-serial device path, not an Arduino
  modem-style path.
- F401RE: if I2C shows `0x40` and `0x77` but no ST-LINK appears in discovery,
  reseat the ST-LINK USB cable, change cable/port, and continue only after the
  healthy `0483:374B` / `STM32 STLink` signature appears.

Build fails:

- Confirm `pio --version` is 6.1.19.
- Delete only that project's `.pio/` directory and rebuild.
- Do not edit generated `sdkconfig`; generated `sdkconfig` files are
  intentionally ignored.
