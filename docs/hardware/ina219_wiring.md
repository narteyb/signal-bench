# INA219 Power Measurement — Wiring and Configuration

## Instrument

Texas Instruments INA219B current/power sensing IC on an Adafruit INA219 breakout.
The breakout is connected to the host machine through an Adafruit MCP2221A USB-I2C bridge.

## Programmatic Configuration

| Parameter | Value | Source |
|---|---|---|
| I2C address | `0x40` | `src/signal_bench/telemetry/sources/ina219.py::Ina219Config.address` |
| Source tag | `ina219` | `src/signal_bench/telemetry/sources/ina219.py::Ina219Source.source_name` |
| Requested sample rate | `8.0 Hz` grouped samples | `src/signal_bench/telemetry/sources/ina219.py::Ina219Config.sample_rate_hz` |
| Partial coverage threshold | `0.85` | `src/signal_bench/telemetry/sources/ina219.py::Ina219Source.partial_coverage_threshold` |
| MCP2221A bridge mode | Shared Blinka I2C bus at `400 kHz`, protected by one process-wide lock | `src/signal_bench/telemetry/i2c.py` |
| MCP2221A environment | `BLINKA_MCP2221=1`, with `SIGNAL_BENCH_REAL_I2C=1` for real sources | `docs/telemetry-setup.md` |
| Shunt resistance | `0.1 ohm` | Adafruit CircuitPython INA219 driver default invoked by `module.INA219(i2c_bus, addr=address)`; `set_calibration_32V_2A()` |
| Calibration profile | `32 V / 2 A` profile; actual max current `3.2 A` with 0.1 ohm shunt | Adafruit CircuitPython INA219 driver default |
| PGA gain | `±320 mV` (`Gain.DIV_8_320MV`) | Adafruit CircuitPython INA219 driver default |
| Bus voltage range | `32 V` (`BusVoltageRange.RANGE_32V`) | Adafruit CircuitPython INA219 driver default |
| Bus ADC resolution | `12-bit, 1 sample` (`ADCRES_12BIT_1S`) | Adafruit CircuitPython INA219 driver default |
| Shunt ADC resolution | `12-bit, 1 sample` (`ADCRES_12BIT_1S`) | Adafruit CircuitPython INA219 driver default |
| Operating mode | Continuous shunt + bus voltage (`SANDBVOLT_CONTINUOUS`) | Adafruit CircuitPython INA219 driver default |
| Measured Gate-1 effective rate | `~6.88 Hz` grouped samples | `docs/findings/telemetry_sample_rate.md` |

## Data-Side Wiring

The I2C data side is common across all MCU targets:

| Signal | Connects to |
|---|---|
| MCP2221A USB | Host machine |
| MCP2221A STEMMA QT | INA219 STEMMA QT |
| INA219 STEMMA QT chain | BME280 STEMMA QT |
| INA219 SDA | MCP2221A SDA over STEMMA QT |
| INA219 SCL | MCP2221A SCL over STEMMA QT |
| INA219 VCC | MCP2221A 3.3 V over STEMMA QT |
| INA219 GND | MCP2221A/I2C ground over STEMMA QT, shared with DUT supply ground |

## Physical Wiring per MCU Board

Dan confirmed on 2026-07-01 that the MCU measurement sessions used the wiring
topology below, matching the signal-bench recommendation: `VIN+` on the
supply-side positive rail, `VIN-` on the DUT/load-side positive input, and a
shared supply/DUT/I2C ground. During board swaps, USB VBUS was kept out of the
unmetered load path or routed through the same metered path.

The invariant is the high-side shunt principle, not a board-revision-specific
header number:

- `VIN+` connects to the supply-side positive rail, upstream of the DUT.
- `VIN-` connects to the load/DUT-side positive input, downstream of the shunt.
- `GND` is common between the supply, DUT, and INA219/I2C ground.
- No board load current may bypass the shunt through an unmetered USB power
  path; if a board USB port also carries power, that path must be disconnected
  or routed through the same metered path.
- If INA219 current reads negative, swap `VIN+` and `VIN-`.

Recommended per-board load-side positive targets:

| Board | Load-side positive target |
|---|---|
| ESP32-S3 DevKitC | Board `5V` / `V+` input |
| Arduino Nano 33 BLE Sense Rev2 | `VIN` / `VUSB` / equivalent load-side input |
| NUCLEO-F401RE | `E5V` / `VIN` / equivalent external 5 V input |

Board silkscreen labels can vary by revision. Use the table as the recommended
target class, and preserve the high-side shunt placement as the reproducible
measurement specification.

### ESP32-S3 DevKitC

| INA219 pin | Connects to |
|---|---|
| `VIN+` | Supply-side +5 V rail from the metered supply path |
| `VIN-` | ESP32-S3 load-side board `5V` / `V+` input target |
| `SDA` | MCP2221A SDA |
| `SCL` | MCP2221A SCL |
| `VCC` | MCP2221A 3.3 V over STEMMA QT |
| `GND` | ESP32-S3 ground target, common with supply ground and MCP2221A/I2C ground |

### NUCLEO-F401RE

| INA219 pin | Connects to |
|---|---|
| `VIN+` | Supply-side +5 V rail from the metered supply path |
| `VIN-` | NUCLEO-F401RE load-side external 5 V input target, `E5V` / `VIN` rail |
| `SDA` | MCP2221A SDA |
| `SCL` | MCP2221A SCL |
| `VCC` | MCP2221A 3.3 V over STEMMA QT |
| `GND` | NUCLEO-F401RE ground target, common with supply ground and MCP2221A/I2C ground |

F401RE benchmark sessions use the board's ST-LINK virtual COM port for the
serial protocol. The controlled full-board boundary is therefore external 5 V
through the INA219/FNB58 path with ST-LINK USB attached and enumerated. Changing
ST-LINK/USB state materially changes board power, so preserve and report that
state for F401RE runs.

### Arduino Nano 33 BLE Sense Rev2

| INA219 pin | Connects to |
|---|---|
| `VIN+` | Supply-side +5 V rail from the metered supply path |
| `VIN-` | Nano 33 BLE Sense Rev2 load-side `VIN` / `VUSB` input target |
| `SDA` | MCP2221A SDA |
| `SCL` | MCP2221A SCL |
| `VCC` | MCP2221A 3.3 V over STEMMA QT |
| `GND` | Nano 33 BLE Sense Rev2 ground target, common with supply ground and MCP2221A/I2C ground |

## Notes

- INA219 measures at the MCU board power rail, inside the board power delivery path used for the run.
- Measurements include the board-level load behind the chosen shunt insertion point: MCU core, regulators, USB-UART bridge if powered through that path, and status LEDs if powered through that path.
- Devkit-level measurement is intentional. It lets a reader with the same board reproduce the numbers without designing a custom production power tree.
- The FNB58 source is retained as a simultaneous window-level cross-check. See `results/a19_meter_crosscheck.json` for the accepted P3 MCU INA219-vs-FNB58 deltas.
