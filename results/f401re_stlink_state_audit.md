# F401RE ST-LINK State Audit

Generated: 2026-07-05 UTC

Purpose: answer the publication-hold question raised after the meter integrity
investigation: whether the published F401RE canonical runs had a consistent
ST-LINK state, and whether the F401RE AD variance is explained by ST-LINK or
boundary changes.

## Answer

The F401RE ST-LINK USB connection state was effectively consistent for the
published protocol runs: it was attached. The evidence is that the F401RE A01
and P3 firmware path used the board's ST-LINK virtual COM port (`Serial`) for
the benchmark protocol, and the run metadata records `CommandMCUAdapter` for
the F401RE benchmark runs.

However, the F401RE energy boundary was not consistent across the accepted
repeat sessions. The accepted KWS and AD repeat sets mix a May 25 low-boundary
power scale with May 29 full-board-scale reruns. That is enough to explain the
F401RE AD energy variance, and it means a one-sentence "ST-LINK attached"
boundary disclosure is not sufficient for F401RE repeat evidence.

Recommended publication action: quarantine the low-boundary May 25 F401RE KWS
and AD energy rows the same way the May 25 F401RE IC energy row is already
quarantined. If Post 1 needs three repeat energy sessions for F401RE KWS and AD,
rerun those cells under a controlled full-board/ST-LINK-attached boundary.

## Evidence for ST-LINK Attached State

- `docs/hardware/firmware_pins.md` says the NUCLEO-F401RE A01 firmware used the
  board's ST-LINK virtual COM port (`Serial`) for the streamed protocol.
- `scripts/run_p3_mcu_matrix.py` configures F401RE on PlatformIO environment
  `nucleo_f401re` with serial port `[device-path-redacted]`; that is the ST-LINK
  VCP path.
- F401RE P3 run metadata in `data/p3_mcu_matrix.db` records
  `adapter = CommandMCUAdapter` and `protocol = n3` for the benchmark runs. The
  adapter requires the serial protocol, so successful F401RE protocol sessions
  imply ST-LINK VCP attached.

This evidence establishes the data/USB connection state. It does not by itself
prove a consistent power boundary.

## Power-Boundary Evidence

The telemetry power scale changes sharply between May 25 and May 29 F401RE
sessions:

| Task | Run | Date | Included in current repeat/headline basis? | INA219 avg power | FNB58 avg power | Boundary interpretation |
|---|---|---:|---:|---:|---:|---|
| KWS | `019e5db3-0d4d-72e1-8033-380875e45cf3` | 2026-05-25 | Yes | 71.576 mW | 68.748 mW | Low-boundary scale |
| KWS | `019e71d7-9146-7c70-9034-a703f581fd72` | 2026-05-29 | Yes | 386.507 mW | not present | Full-board-scale |
| KWS | `019e71df-33a5-7543-b033-19e93aa72de1` | 2026-05-29 | Yes | 386.626 mW | not present | Full-board-scale |
| IC | `019e5db4-e375-7942-9182-e4fef42ce9c7` | 2026-05-25 | Energy quarantined | 70.520 mW | 67.287 mW | Low-boundary scale |
| IC | `019e7598-6637-7dd0-974b-881675b0bedc` | 2026-05-29 | Yes | 341.288 mW | 337.590 mW | Full-board-scale |
| IC | `019e759a-52b9-71e0-8769-486b450e2244` | 2026-05-29 | Yes | 339.514 mW | 333.613 mW | Full-board-scale |
| IC | `019e75fe-9c3b-7061-9423-2831fac5798d` | 2026-05-29 | Yes | 342.054 mW | 340.097 mW | Full-board-scale |
| AD | `019e5dc5-11f9-7a41-8fd5-543d80de7eaa` | 2026-05-25 | Yes | 41.795 mW | 38.324 mW | Low-boundary scale |
| AD | `019e71d6-2d18-70b2-aef5-0d594ad79a56` | 2026-05-29 | Yes | 376.457 mW | not present | Full-board-scale |
| AD | `019e71dd-d72d-74d1-9087-1efa126593cb` | 2026-05-29 | Yes | 377.313 mW | not present | Full-board-scale |

The existing report already recognizes this issue for F401RE IC:

`F401RE/IC 2026-05-25 run predates full-board metered-rail discipline; power is
MCU-only scale (~0.071 W average) rather than full-board scale (~0.34 W).`

The same pattern applies to KWS and AD. The May 25 KWS row is also about
`0.071 W`, while May 29 KWS rows are about `0.386 W`. The May 25 AD accepted row
is even lower, about `0.042 W`, while May 29 AD rows are about `0.376-0.377 W`.

## AD Variance Explanation

The current AD/F401RE repeat set mixes:

- May 25 low-boundary accepted row: `0.1417 mWh/1000`, about `41.8 mW`.
- May 29 full-board accepted rows: `1.2446` and `1.2486 mWh/1000`, about
  `376-377 mW`.

That near order-of-magnitude energy split is sufficient to explain the large
F401RE AD energy variance. It is better described as mixed measurement boundary,
not model/runtime instability.

## Decision

ST-LINK connection state: consistent attached for the F401RE protocol runs.

Energy boundary: inconsistent across accepted KWS and AD sessions.

Publication action: do not lift the F401RE portion of the hold with only a
one-sentence ST-LINK disclosure. Either:

1. quarantine the May 25 low-boundary F401RE KWS and AD energy rows and publish
   the May 29 full-board-scale F401RE energy rows with an explicit
   ST-LINK-attached/devkit-boundary disclosure, accepting reduced repeat count;
   or
2. rerun F401RE KWS and AD under the controlled full-board/ST-LINK-attached
   boundary to restore three-session repeat coverage.

Latency and full-eval accuracy are not implicated by this power-boundary issue.
