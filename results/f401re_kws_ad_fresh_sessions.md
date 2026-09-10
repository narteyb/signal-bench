# F401RE KWS/AD Fresh Documented-Boundary Sessions

Status: complete

Started: 2026-07-06

## Phase A Quarantine

The May 29 F401RE KWS and AD accepted rows are retained in raw provenance but
quarantined from published energy, repeat coverage, and headline repeat sets.

Quarantine reason recorded in local run metadata:

> boundary topology unrecorded; superseded by documented-boundary sessions

| Task | Run ID | Previous label | Treatment |
|---|---|---|---|
| AD | `019e71d6-2d18-70b2-aef5-0d594ad79a56` | `session_2` | Energy quarantined; repeat-set quarantined. |
| KWS | `019e71d7-9146-7c70-9034-a703f581fd72` | `session_2` | Energy quarantined; repeat-set quarantined. |
| AD | `019e71dd-d72d-74d1-9087-1efa126593cb` | `session_3` | Energy quarantined; repeat-set quarantined. |
| KWS | `019e71df-33a5-7543-b033-19e93aa72de1` | `session_3` | Energy quarantined; repeat-set quarantined. |

The accepted documented-boundary July 6 rows remain session one of the fresh
three-session set:

| Task | Run ID | Date | Notes |
|---|---|---|---|
| KWS | `019f366f-357b-7820-b347-949b9832f1e8` | 2026-07-06 | Session one; detailed topology fields backfilled from the accepted boundary-rerun report. |
| AD | `019f3676-d96e-7f10-9907-3586f4f15606` | 2026-07-06 | Session one; detailed topology fields backfilled from the accepted boundary-rerun report. |

## Runner Guard

Future F401RE measurement runs require explicit topology metadata before the
runner will touch hardware:

- `--f401re-power-connector`
- `--f401re-jp5-position`
- `--f401re-usb-vbus-routing`
- `--f401re-stlink-state`

Optional `--f401re-topology-note` values are stored alongside the required
topology fields.

## Next Interlock

Do not run another F401RE KWS/AD session on 2026-07-06. The accepted session-one
runs already occupy day one, and the brief requires each cell's accepted
three-session set to span at least three distinct days.

At the start of the next eligible measurement day, request Dan's rig power-up
interlock before touching hardware:

1. External metered rail first through FNB58 and INA219.
2. Then ST-LINK USB/VCP to the Mac.
3. Confirm and record power connector, JP5 position, USB/VBUS routing, and
   ST-LINK enumeration state before each accepted session.

## Day Two Sessions

Date: 2026-07-07

Interlock record:

- User reported rig ready, JP5 position `E5V`, and USB routing to Mac.
- Host observed ST-LINK USB enumeration as `STM32 STLink`, serial
  `[hardware-serial-redacted]`, with serial path `[device-path-redacted]`.
- Idle smoke before workload showed full-board-scale metered power: INA219
  `474.4 mW`, FNB58 `472.7 mW`, BME280 `24.44 C`.

Topology metadata recorded on accepted Day 2 runs:

- Power connector: `E5V external 5 V input via INA219/FNB58 metered rail`
- JP5 position: `E5V`
- USB/VBUS routing: `ST-LINK USB/VCP connected to Mac; external metered rail
  powers board through E5V; USB VBUS present as part of documented
  ST-LINK-attached boundary`
- ST-LINK state: `attached_enumerated ([device-path-redacted]; STM32 STLink
  serial [hardware-serial-redacted])`

Accepted sessions:

| Date | Task | Run ID | Wh/1000 | p50 latency | INA219 avg power | FNB58 avg power | FNB58 delta vs INA219 | BME280 temp | Telemetry |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-07-07 | KWS | `019f3d8a-7a6e-7f92-81de-8e9e49eb795a` | 0.021382 | 158.926 ms | 462.305 mW | 452.329 mW | -2.16% | 24.782 C | Accepted |
| 2026-07-07 | AD | `019f3d8d-b3fd-79b2-885f-007399c54367` | 0.001316 | 8.136 ms | 388.083 mW | 384.578 mW | -0.90% | 24.899 C | Accepted |

Rejected Day 2 provenance:

| Task | Run ID | Reason | INA219 avg power | FNB58 avg power |
|---|---|---|---:|---:|
| KWS | `019f3d83-32b9-74d0-b483-b8f81725204e` | INA219 telemetry coverage below acceptance threshold. | 463.704 mW | 455.440 mW |
| KWS | `019f3d84-ab01-7533-b0f0-d96b93e2a480` | INA219 telemetry coverage below acceptance threshold. | 458.391 mW | 452.675 mW |
| KWS | `019f3d86-cc72-7831-bac5-f89d8aa87442` | INA219 telemetry coverage below acceptance threshold. | 462.484 mW | 456.250 mW |
| KWS | `019f3d88-5d8a-75d1-b212-6cf0e48e0efb` | INA219 telemetry coverage below acceptance threshold. | 462.241 mW | 453.240 mW |

The rejected KWS attempts were all at the expected documented-boundary power
regime. They were excluded from fresh coverage and energy summaries because the
orchestrator marked telemetry partial. The Day 2 accepted KWS/AD runs followed a
runner/orchestrator fix that starts the DB and coverage windows after serial
prepare and telemetry source startup, aligning the acceptance denominator with
the actual measurable workload window.

## Day Three Sessions

Date: 2026-07-08

Interlock record:

- User confirmed the Day 3 setup was the same as Day 2: JP5 position `E5V` and
  USB routing to Mac.
- Host observed ST-LINK USB enumeration as `STM32 STLink`, serial
  `[hardware-serial-redacted]`, with serial path `[device-path-redacted]`.
- Idle smoke before workload showed full-board-scale metered power: INA219
  `473.9 mW`, FNB58 `471.3 mW`, BME280 `25.08 C`.

Accepted sessions:

| Date | Task | Run ID | Wh/1000 | p50 latency | INA219 avg power | FNB58 avg power | FNB58 delta vs INA219 | BME280 temp | Telemetry |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-07-08 | KWS | `019f43e6-85da-76c2-a654-e834f3f159a7` | 0.021118 | 158.928 ms | 457.613 mW | 452.470 mW | -1.12% | 25.739 C | Accepted |
| 2026-07-08 | AD | `019f43ea-02f5-7ac0-a2c0-e4fd615f9b08` | 0.001295 | 8.136 ms | 384.272 mW | 383.358 mW | -0.24% | 26.176 C | Accepted |

## Final Fresh F401RE Statistics

Accepted repeat basis is now the documented-boundary sessions from July 6,
July 7, and July 8 for each cell.

| Task | Published repeat runs | p50 Wh/1000 | p50 mWh/1000 | p50 latency | Energy CV | Latency CV |
|---|---:|---:|---:|---:|---:|---:|
| KWS | 3 | 0.021382 | 21.382 | 158.926 ms | 0.99% | 0.00144% |
| AD | 3 | 0.001295 | 1.295 | 8.136 ms | 1.03% | 0.00% |

Per-run accepted energy:

| Task | Run ID | Date | Wh/1000 | Median latency |
|---|---|---|---:|---:|
| KWS | `019f366f-357b-7820-b347-949b9832f1e8` | 2026-07-06 | 0.021537 | 158.9230 ms |
| KWS | `019f3d8a-7a6e-7f92-81de-8e9e49eb795a` | 2026-07-07 | 0.021382 | 158.9260 ms |
| KWS | `019f43e6-85da-76c2-a654-e834f3f159a7` | 2026-07-08 | 0.021118 | 158.9275 ms |
| AD | `019f3676-d96e-7f10-9907-3586f4f15606` | 2026-07-06 | 0.001290 | 8.1360 ms |
| AD | `019f3d8d-b3fd-79b2-885f-007399c54367` | 2026-07-07 | 0.001316 | 8.1360 ms |
| AD | `019f43ea-02f5-7ac0-a2c0-e4fd615f9b08` | 2026-07-08 | 0.001295 | 8.1360 ms |

## Changed Claims

| Claim | Prior published/interim value | Fresh documented-boundary value |
|---|---:|---:|
| F401RE KWS Wh/1000 | 0.017489 | 0.021382 |
| F401RE KWS p50 latency | 158.924 ms | 158.926 ms |
| F401RE KWS energy CV | 12.44% | 0.99% |
| F401RE AD Wh/1000 | 0.001249 | 0.001295 |
| F401RE AD p50 latency | 8.138 ms | 8.136 ms |
| F401RE AD energy CV | 2.00% | 1.03% |

Changed-language requirements:

- Any text saying July 6 alone restored KWS/AD 3/3 coverage is superseded.
- Any KWS variance caveat based on the July 6 vs May 29 regime gap is superseded.
- The active published basis is three fresh documented-boundary sessions per
  cell spanning July 6, July 7, and July 8.

## Propagated Artifacts

- `data/matrices/post-1-data.yml`
- `data/charts/`
- `data/reports/post-1-report.md`
- `content/posts/2026-05-28-tinyml-reality-check.md`
- `content/signal-reports/2026-05-28-tinyml-reality-check-data.yml`
- `results/repeatability_stats.json`
- `results/pre_publish_review.md`

## Open Work

- Tech Lead publication-hold sign-off on the recomputed F401RE KWS/AD values.
