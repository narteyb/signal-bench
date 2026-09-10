# F401RE KWS/AD Boundary Quarantine and Rerun

Date: 2026-07-06

## Quarantine

The May 25 F401RE KWS and AD low-boundary rows remain in raw provenance but are
excluded from the boundary-consistent published repeat sets.

| Task | Run ID | Treatment |
|---|---|---|
| KWS | `019e5db3-0d4d-72e1-8033-380875e45cf3` | Energy quarantined; repeat-set quarantined. |
| AD | `019e5db6-a631-7210-85dd-7cc33f0e0049` | Energy quarantined; repeat-set quarantined; telemetry partial. |
| AD | `019e5dc5-11f9-7a41-8fd5-543d80de7eaa` | Energy quarantined; repeat-set quarantined. |

Reason recorded in run metadata: the May 25 F401RE KWS/AD rows predate the
full-board metered-rail discipline and are low-boundary scale, not the
controlled full-board/ST-LINK-attached boundary.

## Methodology Language

Added to `docs/methodology.md`:

> For NUCLEO-F401RE sessions, the serial protocol path uses the board's ST-LINK virtual COM port, so the full-board boundary is the NUCLEO-F401RE powered through the metered external rail with ST-LINK USB attached and enumerated.

## Rerun Sessions

Controlled boundary: FNB58/INA219 metered external 5 V rail, ST-LINK USB
attached and enumerated, redacted ST-LINK serial protocol path, INA219
authoritative, FNB58 cross-check, BME280 ambient.

| Task | Accepted run ID | Iterations | INA219 avg power | FNB58 avg power | BME280 temp | Status |
|---|---:|---:|---:|---:|---:|---|
| KWS | `019f366f-357b-7820-b347-949b9832f1e8` | 202 | 465.825 mW | 456.517 mW | 24.456 C | Accepted |
| AD | `019f3676-d96e-7f10-9907-3586f4f15606` | 3942 | 380.984 mW | 385.964 mW | 25.476 C | Accepted |

Rejected provenance: AD run `019f3675-53cc-7a92-860a-f0e60f02f711` completed
the workload but was not accepted because INA219 telemetry coverage was 73%,
below the 75% acceptance threshold. It remains telemetry-partial and is excluded
from repeat coverage.

Hardware/debug note: default ST-LINK upload/reset was unreliable on this rig.
The AD image was flashed with slow direct OpenOCD `flash write_image erase` plus
`verify_image`, then started with a Cortex-M software reset request. The accepted
measurement run used the normal serial protocol after verification.

## Updated F401RE Statistics

Accepted repeat basis is now the two May 29 full-board sessions plus the
accepted July 6 session for each cell.

| Task | Published repeat runs | p50 Wh/1000 | p50 mWh/1000 | p50 latency | Energy CV | Latency CV |
|---|---:|---:|---:|---:|---:|---:|
| KWS | 3 | 0.017489 | 17.489 | 158.924 ms | 12.44% | 0.00079% |
| AD | 3 | 0.001249 | 1.249 | 8.138 ms | 2.00% | 0.01419% |

Per-run accepted energy:

| Task | Run ID | Wh/1000 | Median latency |
|---|---|---:|---:|
| KWS | `019e71d7-9146-7c70-9034-a703f581fd72` | 0.017472 | 158.9255 ms |
| KWS | `019e71df-33a5-7543-b033-19e93aa72de1` | 0.017489 | 158.9240 ms |
| KWS | `019f366f-357b-7820-b347-949b9832f1e8` | 0.021537 | 158.9230 ms |
| AD | `019e71d6-2d18-70b2-aef5-0d594ad79a56` | 0.001245 | 8.1380 ms |
| AD | `019e71dd-d72d-74d1-9087-1efa126593cb` | 0.001249 | 8.1380 ms |
| AD | `019f3676-d96e-7f10-9907-3586f4f15606` | 0.001290 | 8.1360 ms |

## Changed Claims

- The F401RE AD energy-variance warning changes: the previous roughly 72.6%
  mixed-boundary variance was a boundary artifact. The replacement
  boundary-consistent AD energy CV is 2.00%.
- Any claim naming F401RE AD as the largest Wh/1000 spread because of the May 25
  low-boundary row must be removed or rewritten.
- F401RE KWS remains boundary-consistent at 3/3 sessions, but the July 6 run is
  higher power than the two May 29 runs; the new KWS energy CV is 12.44%.

## Propagated Artifacts

- `data/matrices/post-1-data.yml`
- `data/charts/`
- `data/reports/post-1-report.md`
- `reports/p3_mcu_inventory.md`

Open question: F401RE IC still has one extra eligible latency repeat because
its May 25 energy-only quarantine follows the earlier IC precedent. This brief
only changed KWS/AD repeat-set eligibility.
