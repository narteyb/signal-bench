# A08 Physical Confirmations

Resolved on 2026-07-01 by Dan confirmation. The measurement sessions followed
the signal-bench recommendation recorded in `docs/hardware/ina219_wiring.md`:
INA219 `VIN+` on the supply-side +5 V rail, INA219 `VIN-` on the board
load-side positive input, and shared supply/DUT/I2C ground. USB VBUS was kept
out of the unmetered load path or routed through the same metered path during
board swaps.

## ESP32-S3 DevKitC

Confirmed: INA219 `VIN+` was connected to the supply-side +5 V rail from the
metered supply path.

Confirmed: INA219 `VIN-` was connected to the ESP32-S3 load-side `5V` / `V+`
board input.

Confirmed: the shunt was inserted in the board +5 V input path before onboard
regulation, not in the 3.3 V rail.

Confirmed: ESP32-S3 `GND` was common with supply ground and MCP2221A/I2C ground.

## NUCLEO-F401RE

Confirmed: INA219 `VIN+` was connected to the supply-side +5 V rail from the
metered supply path.

Confirmed: INA219 `VIN-` was connected to the NUCLEO-F401RE load-side external
5 V input, `E5V` / `VIN` rail.

Confirmed: the shunt was inserted at the external 5 V input path (`E5V` /
`VIN` rail), not the 3.3 V rail.

Confirmed: NUCLEO-F401RE `GND` was common with supply ground and MCP2221A/I2C
ground.

## Arduino Nano 33 BLE Sense Rev2

Confirmed: INA219 `VIN+` was connected to the supply-side +5 V rail from the
metered supply path.

Confirmed: INA219 `VIN-` was connected to the Nano 33 BLE Sense Rev2 load-side
`VIN` / `VUSB` input rail.

Confirmed: the shunt was inserted in the Nano input path (`VIN` / `VUSB` rail),
not the 3.3 V rail.

Confirmed: Nano 33 BLE Sense Rev2 `GND` was common with supply ground and
MCP2221A/I2C ground.
