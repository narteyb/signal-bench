# Hardware Compatibility Matrix

This matrix separates three states:

- **Supported in public CLI:** available without private lab hardware.
- **Bench-validated:** measured or brought up in the Agoo AI lab, but not yet a
  general public adapter path.
- **Planned:** part of the roadmap, not a stable public target.

## Targets

| Target | Kind | Public CLI status | Bench status | Notes |
|---|---|---|---|---|
| Mock target | Software | Supported | Validated | No hardware required; use for smoke tests and adapter development. |
| ESP32-S3 DevKitC | MCU | Launch-tier reproduction | Bench-validated | Use `docs/hardware/reproduce-esp32s3.md`. |
| Arduino Nano 33 BLE Sense Rev2 | MCU | Launch-tier reproduction | Bench-validated | Use `docs/hardware/reproduce-nano33.md`. |
| NUCLEO-F401RE | MCU | Launch-tier reproduction | Bench-validated | Use `docs/hardware/reproduce-f401re.md`; ST-LINK state is part of the boundary. |
| Raspberry Pi 5 CPU | SBC | Planned | Bench-validated | Whole-board power measured with FNB58 inline USB-C in the current method. |
| Hailo-10H on Pi 5 | NPU | Planned | Bench-validated | Adapter path exists for first-light; curve-comparable data depends on compiled HEF artifacts. |
| Jetson Orin Nano | SBC/GPU | Planned | Bring-up validated | Use `docs/hardware/reproduce-jetson-orin-nano.md`; validated on JetPack 6.2 / L4T R36.4.3 with expanded SD rootfs. |
| M1 Max | Local workstation | Planned | Bench-validated | Power boundary is device/package counters, not whole-board wall power. |
| Modal A10G | Cloud GPU | Planned | Bench-validated | Power boundary is GPU package power via NVML. |

## Telemetry hardware

| Device | Public CLI status | Bench status | Notes |
|---|---|---|---|
| Mock INA219 / BME280 | Supported | Validated | Default no-hardware telemetry path. |
| FNIRSI FNB58 BLE | Supported with local hardware | Bench-validated | Source tag is `fnb58`; BLE is the conservative fallback. |
| FNIRSI FNB58 USB-HID | Experimental | Bench-validated | Higher-cadence transport; keep BLE fallback available. |
| INA219 over MCP2221A | Supported with local hardware | Bench-validated | MCU rail-side authority; see `docs/telemetry-setup.md`. |
| BME280 over MCP2221A | Supported with local hardware | Bench-validated | Ambient/environmental telemetry; default address expected at `0x77`. |

## Compatibility rule

A target is not "supported" just because it once produced a number. Public
support requires a documented adapter path, reproducible setup instructions,
telemetry coverage rules, and tests or smoke checks that catch silent fallback
states.
