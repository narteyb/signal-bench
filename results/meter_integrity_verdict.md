# Meter Integrity Verdict

Generated: 2026-07-04 / 2026-07-05 UTC

Status: verdict reached for the INA219/FNB58 offset investigation. This artifact
does not modify any published canonical data.

## Verdict

The consistent FNB58-lower-than-INA219 offset is best explained by H2: FNB58
BLE/window reporting under-reads bursty load windows relative to the rail-side
INA219 path. The INA219 publication path is not compromised by the offset.

Evidence:

- Dual-INA219 Phase A, valid position-swap run:
  `data/meter_integrity/phase-a-nano-dual-ina-position-2-20260705T004559Z/summary.json`
  showed `0x40 = 26.457 mW` and `0x41 = 26.452 mW`, a `-0.020%`
  difference. In the same window, FNB58 was `24.854 mW`, about `-6.05%`
  versus both rail sensors.
- INA219 configuration audit matched first principles. The documented shunt is
  `0.1 ohm`; the expected calibration register for the driver profile is
  `4096`, and the Adafruit driver writes `4096`.
- Phase B raw-shunt diagnostic:
  `data/meter_integrity/phase-b-raw-shunt-nano-20260705T004738Z/summary.json`
  did not show a common 5-6% INA219 overstatement across both units. `0x40`
  raw-shunt integration was `+0.30%` versus driver power. `0x41` was `+5.42%`
  in that diagnostic, but Phase A position swap showed the two INA219s agree
  under the same integrated telemetry path.
- Phase C cycling ESP32-S3 load:
  `data/meter_integrity/phase-c-esp32-fnb58-windowing-cycling-20260705T012444Z/summary.json`
  showed integrated FNB58 `-7.11%` versus INA219. In idle-like segments
  (`<190 mW` INA), matched FNB58 was `+1.86%` on mean samples. In load-like
  segments (`>220 mW` INA), matched FNB58 was `-20.75%`. That is the
  distinguishing H2 measurement.

Rejected or bounded hypotheses:

- H1, INA219 calibration/configuration bias: not supported as the root cause.
  The configured calibration matches the documented 0.1 ohm shunt and driver
  profile, and two INA219 units agreed within `0.02%` after physical position
  swap.
- H3/H4, current bypass or boundary mismatch compromising the INA219 path: not
  supported for the accepted publication boundary. Board USB state changes board
  behavior and power, especially on F401RE, but the paired audits did not show a
  bypass pattern where load current disappears from the INA219 while remaining
  present upstream.

## Measurement Summary

| Phase | Artifact | Key result |
|---|---|---|
| R1 | `src/signal_bench/telemetry/sources/ina219.py`, `docs/hardware/ina219_wiring.md` | INA219 uses Adafruit default `32V/2A`, `0.1 ohm`, calibration `4096`, 12-bit 1-sample continuous bus+shunt mode. |
| R1 | `src/signal_bench/telemetry/sources/fnirsi.py` | FNB58 BLE source decodes voltage/current frames at configured `4 Hz` and computes `power = V * I`; no device energy counter is used. |
| Phase A | `data/meter_integrity/phase-a-nano-dual-ina-position-2-20260705T004559Z/summary.json` | INA219s agreed within `0.020%`; FNB58 was `-6.04%` to `-6.06%` lower. |
| Phase B | `data/meter_integrity/phase-b-raw-shunt-nano-20260705T004738Z/summary.json` | Raw shunt vs driver power did not show a shared 5-6% INA overstatement. |
| Phase C | `data/meter_integrity/phase-c-esp32-fnb58-windowing-cycling-20260705T012444Z/summary.json` | FNB58 integrated `-7.11%`; load-like segments were `-20.75%`, confirming burst/window under-read. |
| Phase D ESP32-S3 | `data/meter_integrity/phase-d-esp32-usb-attached-20260705T012942Z/summary.json` | USB attached increased INA rail power by `+22.64%`; not a bypass-collapse pattern. |
| Phase D Nano 33 | `data/meter_integrity/phase-d-nano-usb-disconnected-20260705T013942Z/summary.json` | USB disconnected changed INA rail power by `-1.74%`; not bypass-scale. |
| Phase D F401RE | `data/meter_integrity/phase-d-f401re-usb-disconnected-20260705T015945Z/summary.json` | ST-LINK disconnected changed INA rail power by `-27.85%`; FNB58 and INA219 still agreed within `0.32%`. |

Invalid or non-verdict diagnostics:

- `data/meter_integrity/phase-a-nano-dual-ina-20260705T000541Z/summary.json`
  is excluded from the Phase A instrument verdict because `0x41` was visible on
  I2C but not in the Nano load path.
- `data/meter_integrity/phase-c-esp32-fnb58-windowing-20260705T011425Z/summary.json`
  is a useful steady-load cross-check (`FNB58 -0.92%`) but did not exercise the
  documented ESP32 idle/load/release cycle.

## Per-Cell Impact

Current published MCU energy values are INA219-based. The FNB58 offset affects
only cross-check interpretation and methodology language, not the INA219
headline numbers.

| Cell | Impact | Rerun required? | Reason |
|---|---|---:|---|
| Tier 1 ESP32-S3 KWS | Unaffected for current INA219 headline; language affected. | No | H2 affects FNB58 cross-check only. ESP32 USB-attached audit increased metered rail power rather than bypassing it. |
| Tier 1 ESP32-S3 IC | Unaffected for current INA219 headline; language affected. | No | Same ESP32 board boundary finding as KWS. |
| Tier 1 ESP32-S3 AD | Unaffected for current INA219 headline; language affected. | No | Same ESP32 board boundary finding as KWS. |
| Tier 1 Nano 33 KWS | Unaffected for current INA219 headline; language affected. | No | Dual-INA agreement validates rail sensor path; Nano USB attach/disconnect changed rail power by only `1.74%`. |
| Tier 1 Nano 33 IC | Unaffected for current INA219 headline; language affected. | No | Same Nano board boundary finding as KWS. Previously quarantined anomalous Nano runs remain excluded. |
| Tier 1 Nano 33 AD | Unaffected for current INA219 headline; language affected. | No | Same Nano board boundary finding as KWS. Previously quarantined anomalous Nano runs remain excluded. |
| Tier 1 F401RE KWS | INA219 meter path intact, but repeat energy evidence mixes low-boundary May 25 and full-board May 29 power scales. | Yes, unless May 25 energy is quarantined and reduced repeat count is accepted. | ST-LINK VCP was attached for protocol runs, but `019e5db3...` is about `71.6 mW` while May 29 KWS reruns are about `386.5 mW`. |
| Tier 1 F401RE IC | INA219 meter path intact; current energy headline already excludes the known May 25 low-boundary energy row. | No if existing quarantine remains. | The May 25 MCU-only-scale energy row is already quarantined; May 29 IC reruns are consistent at about `339-342 mW`. |
| Tier 1 F401RE AD | INA219 meter path intact, but repeat energy evidence mixes low-boundary May 25 and full-board May 29 power scales. | Yes, unless May 25 energy is quarantined and reduced repeat count is accepted. | ST-LINK VCP was attached for protocol runs, but `019e5dc5...` is about `41.8 mW` while May 29 AD reruns are about `376-377 mW`; this explains the large AD energy variance. |

## Rerun List

No existing Nano 33 or ESP32-S3 INA219-based cells need remeasurement for
meter-integrity reasons. F401RE needs an energy-boundary correction:
quarantine the low-boundary May 25 KWS and AD energy rows, or rerun F401RE KWS
and AD under a controlled full-board/ST-LINK-attached boundary if three-session
energy repeat coverage is required.

Reruns would be required only if the editorial boundary changes, for example:

- making FNB58 the headline MCU meter for bursty workloads;
- publishing USB-disconnected F401RE devkit numbers instead of the current
  ST-LINK-attached serial-protocol boundary;
- changing MCU protocol to remove USB serial from ESP32-S3 or Nano 33 runs.

Those would be new methodology choices. The F401RE KWS/AD low-boundary rows are
not a new methodology choice; they are inconsistent repeat evidence and should
not remain in the F401RE energy basis.

## Methodology and Post Language Changes

Update methodology and post language as follows:

- State that MCU headline power/energy uses INA219 rail-side telemetry. FNB58
  is a simultaneous wall/upstream cross-check, not the authoritative MCU meter.
- Explain that negative FNB58-minus-INA219 deltas are now attributed primarily
  to FNB58 BLE/window behavior on bursty loads, not to measured negative
  upstream overhead.
- Do not use FNB58 BLE energy as the headline value for bursty MCU cells unless
  a higher-rate or independently validated FNB58 path is used.
- State USB/ST-LINK state as part of the devkit measurement boundary. This is
  especially important for F401RE: ST-LINK connected versus disconnected changed
  metered rail draw by about `28%`.
- Preserve the existing quarantine language for earlier known non-conforming
  runs. The Nano session-3 bypass anomaly and the F401RE/IC MCU-only-scale run
  remain excluded; this verdict does not rehabilitate them.
- Add matching quarantine language for F401RE KWS `019e5db3...` and F401RE AD
  `019e5dc5...` energy if Post 1 keeps the May 29 full-board/ST-LINK-attached
  F401RE boundary.

## Confidence

Confidence is high that the INA219 publication path is not compromised by the
FNB58-low anomaly. Confidence is high that FNB58 BLE/window behavior explains
the offset direction and magnitude on bursty loads.

Residual uncertainty:

- The investigation did not use an absolute reference such as a calibrated DMM,
  precision resistor, or electronic load. Absolute meter accuracy is therefore
  not proven.
- The installed INA219 shunt value was not independently measured; it is taken
  from the Adafruit breakout default and repo wiring documentation.
- FNB58 USB-HID was not promoted to a validated replacement path in this
  investigation.

Those residuals do not require rerunning Nano 33 or ESP32-S3 INA219-headline
publication cells. F401RE KWS/AD need either energy quarantine of the May 25
low-boundary rows or controlled reruns to restore repeat coverage.
