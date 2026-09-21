# post-1-tinyml-matrix Synth Report

- Generated: `2026-07-08T22:52:18.286853Z`
- Cells: `21`
- Runs: `48`
- Repeat coverage: `33/63 eligible runs, 36 missing`
- Status: OK=9, PARTIAL=0, INCOMPLETE=0, NO_DATA=12

## Summary Matrix

| Task | F401RE | Nano 33 | ESP32-S3 | Pi 5 | Jetson Orin Nano | M1 Max | Modal A10G |
|---|---|---|---|---|---|---|---|
| kws | OK<br>158926.0 us<br>21.382 mWh | OK<br>224222.0 us<br>2.3666 mWh | OK<br>106496.0 us<br>13.221 mWh | NO_DATA | NO_DATA | NO_DATA | NO_DATA |
| ic | OK<br>755418.0 us<br>71.36 mWh | OK<br>1232612.5 us<br>13.698 mWh | OK<br>551062.0 us<br>67.631 mWh | NO_DATA | NO_DATA | NO_DATA | NO_DATA |
| ad | OK<br>8136.0 us<br>1.2954 mWh | OK<br>12421.0 us<br>0.18891 mWh | OK<br>11723.0 us<br>1.4382 mWh | NO_DATA | NO_DATA | NO_DATA | NO_DATA |

## Per-Cell Detail

### kws/f401re

- Status: `OK`
- Runs: `11`
- Repeat coverage: `3` eligible of `3` required
- Ineligible runs: `8`
- Coverage warnings: `8 run(s) are not eligible for repeat coverage`
- Partial runs: `5` of `11`; headline basis: `3`
- Partial inference windows: `1`

#### Run `019e5db3-0d4d-72e1-8033-380875e45cf3`

- Status: `completed`
- Started: `2026-05-25T05:54:35.982736Z`
- Duration: `77.00 s`
- Iterations: `441` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `158925.0` us, mean `158930.4` us, p95 `158970.0` us, p99 `158984.6` us, stddev `22.53` us, variance `0.0142%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: F401RE/KWS 2026-05-25 run predates full-board metered-rail discipline; power is low-boundary scale (~0.072 W average) rather than full-board scale (~0.386 W). Energy excluded; latency remains valid.`; `repeat stats quarantined: F401RE/KWS 2026-05-25 run predates full-board metered-rail discipline; excluded from boundary-consistent KWS repeat set and published KWS averages.`

#### Run `019e71d5-1aba-7d52-870e-36d09b4e05a3`

- Status: `completed`
- Started: `2026-05-29T03:44:11.962736Z`
- Duration: `2.5848 s`
- Iterations: `3` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `bme280, ina219`
- Partial reasons: `ina219: coverage=38%, threshold=75%, samples=6/16`; `bme280: coverage=50%, threshold=75%, samples=1/2`
- Partial inference warnings: `1`
- Latency: median `158924.0` us, mean `158926.0` us, p95 `158958.2` us, p99 `158961.2` us, stddev `35.04` us, variance `0.0220%`
- Energy: `0.0001` Wh total, `28.1737` mWh/1000, avg power `0.4035` W, coverage `29.17%`
- Warnings: `energy estimate uses fewer than 10 power samples`

#### Run `019e71d7-9146-7c70-9034-a703f581fd72`

- Status: `completed`
- Started: `2026-05-29T03:46:53.383292Z`
- Duration: `34.68 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `158925.5` us, mean `158928.2` us, p95 `158971.0` us, p99 `158982.0` us, stddev `23.51` us, variance `0.0148%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`; `repeat stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`

#### Run `019e71df-33a5-7543-b033-19e93aa72de1`

- Status: `completed`
- Started: `2026-05-29T03:55:13.701435Z`
- Duration: `34.68 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `158924.0` us, mean `158928.3` us, p95 `158971.0` us, p99 `158978.0` us, stddev `22.45` us, variance `0.0141%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`; `repeat stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`

#### Run `019f366f-357b-7820-b347-949b9832f1e8`

- Status: `completed`
- Started: `2026-07-06T07:58:05.691746Z`
- Duration: `37.86 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `158923.0` us, mean `158930.9` us, p95 `158972.0` us, p99 `158982.0` us, stddev `24.17` us, variance `0.0152%`
- Energy: `0.0044` Wh total, `21.5370` mWh/1000, avg power `0.4663` W, coverage `88.70%`

#### Run `019f3d83-32b9-74d0-b483-b8f81725204e`

- Status: `completed`
- Started: `2026-07-07T16:57:16.218666Z`
- Duration: `40.37 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `ina219`
- Partial reasons: `ina219: coverage=70%, threshold=75%, samples=223/318`
- Latency: median `158925.0` us, mean `158930.7` us, p95 `158971.0` us, p99 `158986.0` us, stddev `24.31` us, variance `0.0153%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: telemetry partial rejected attempt`; `repeat stats quarantined: telemetry partial rejected attempt`

#### Run `019f3d84-ab01-7533-b0f0-d96b93e2a480`

- Status: `completed`
- Started: `2026-07-07T16:58:52.546273Z`
- Duration: `40.59 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `ina219`
- Partial reasons: `ina219: coverage=69%, threshold=75%, samples=220/320`
- Latency: median `158927.5` us, mean `158931.5` us, p95 `158976.0` us, p99 `158984.0` us, stddev `24.73` us, variance `0.0156%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: telemetry partial rejected attempt`; `repeat stats quarantined: telemetry partial rejected attempt`

#### Run `019f3d86-cc72-7831-bac5-f89d8aa87442`

- Status: `completed`
- Started: `2026-07-07T17:01:12.204011Z`
- Duration: `39.32 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `ina219`
- Partial reasons: `ina219: coverage=72%, threshold=75%, samples=223/310`
- Latency: median `158928.5` us, mean `158931.9` us, p95 `158975.0` us, p99 `158984.0` us, stddev `25.37` us, variance `0.0160%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: telemetry partial rejected attempt`; `repeat stats quarantined: telemetry partial rejected attempt`

#### Run `019f3d88-5d8a-75d1-b212-6cf0e48e0efb`

- Status: `completed`
- Started: `2026-07-07T17:03:02.962914Z`
- Duration: `34.28 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `ina219`
- Partial reasons: `ina219: coverage=67%, threshold=75%, samples=224/334`
- Latency: median `158925.0` us, mean `158931.6` us, p95 `158972.0` us, p99 `158984.0` us, stddev `24.58` us, variance `0.0155%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: telemetry partial rejected attempt`; `repeat stats quarantined: telemetry partial rejected attempt`

#### Run `019f3d8a-7a6e-7f92-81de-8e9e49eb795a`

- Status: `completed`
- Started: `2026-07-07T17:05:16.160270Z`
- Duration: `34.20 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `158926.0` us, mean `158932.0` us, p95 `158981.0` us, p99 `158987.0` us, stddev `25.11` us, variance `0.0158%`
- Energy: `0.0043` Wh total, `21.3817` mWh/1000, avg power `0.4631` W, coverage `98.18%`

#### Run `019f43e6-85da-76c2-a654-e834f3f159a7`

- Status: `completed`
- Started: `2026-07-08T22:43:33.720305Z`
- Duration: `34.18 s`
- Iterations: `202` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `158927.5` us, mean `158931.7` us, p95 `158973.0` us, p99 `158985.0` us, stddev `24.61` us, variance `0.0155%`
- Energy: `0.0043` Wh total, `21.1181` mWh/1000, avg power `0.4573` W, coverage `98.24%`
### kws/nano33

- Status: `OK`
- Runs: `7`
- Repeat coverage: `6` eligible of `3` required
- Ineligible runs: `1`
- Extra eligible runs: `3`
- Coverage warnings: `1 run(s) are not eligible for repeat coverage`; `3 extra eligible run(s) beyond required repeat coverage`
- Partial runs: `1` of `7`; headline basis: `6`

#### Run `019e5da5-52ee-7d03-800e-9737850b6d96`

- Status: `completed`
- Started: `2026-05-25T05:39:36.302938Z`
- Duration: `76.56 s`
- Iterations: `313` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `224226.0` us, mean `224221.8` us, p95 `224233.7` us, p99 `224243.6` us, stddev `11.15` us, variance `0.0050%`
- Energy: `0.0007` Wh total, `2.3824` mWh/1000, avg power `0.0379` W, coverage `92.61%`

#### Run `019e5da7-ef3e-7830-94a8-2ef6f6845b8e`

- Status: `completed`
- Started: `2026-05-25T05:42:27.390442Z`
- Duration: `75.02 s`
- Iterations: `313` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `224226.0` us, mean `224224.9` us, p95 `224241.5` us, p99 `224251.0` us, stddev `10.53` us, variance `0.0047%`
- Energy: `0.0007` Wh total, `2.3629` mWh/1000, avg power `0.0376` W, coverage `94.48%`

#### Run `019e674c-cd81-7243-9470-a0d817a5b26d`

- Status: `completed`
- Started: `2026-05-27T02:39:07.138275Z`
- Duration: `33.92 s`
- Iterations: `143` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `224222.0` us, mean `224220.0` us, p95 `224233.0` us, p99 `224236.2` us, stddev `10.05` us, variance `0.0045%`
- Energy: `0.0003` Wh total, `2.3790` mWh/1000, avg power `0.0377` W, coverage `95.85%`

#### Run `019e7548-0873-7571-99dd-e67e5eb23723`

- Status: `completed`
- Started: `2026-05-29T19:48:35.571492Z`
- Duration: `33.87 s`
- Iterations: `143` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `224126.0` us, mean `224121.3` us, p95 `224145.0` us, p99 `224149.4` us, stddev `18.88` us, variance `0.0084%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: Nano33 session 3 INA219 current path anomaly: ~1 mW average power while latency matched sessions 1-2; energy excluded pending diagnosis.`

#### Run `019e755c-e759-7ff3-8303-c589cf777493`

- Status: `completed`
- Started: `2026-05-29T20:11:23.353384Z`
- Duration: `35.44 s`
- Iterations: `143` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `224127.0` us, mean `224125.1` us, p95 `224142.2` us, p99 `224147.6` us, stddev `12.57` us, variance `0.0056%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: Diagnostic FNB58/INA219 cross-check; not an A03 repeatability session.`

#### Run `019e7564-8561-7cc3-b6fb-9359503a5a88`

- Status: `completed`
- Started: `2026-05-29T20:19:42.561317Z`
- Duration: `38.02 s`
- Iterations: `143` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `ina219`
- Partial reasons: `ina219: coverage=70%, threshold=75%, samples=210/299`
- Latency: median `224131.0` us, mean `224126.5` us, p95 `224145.0` us, p99 `224156.2` us, stddev `15.56` us, variance `0.0069%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: Diagnostic fixed-path FNB58/INA219 smoke run; telemetry_partial=true, not A03 repeatability energy.`

#### Run `019e756b-3d0c-7610-be25-85b897d45d51`

- Status: `completed`
- Started: `2026-05-29T20:27:02.796657Z`
- Duration: `33.72 s`
- Iterations: `143` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `224132.0` us, mean `224131.0` us, p95 `224149.0` us, p99 `224161.1` us, stddev `12.96` us, variance `0.0058%`
- Energy: `0.0003` Wh total, `2.3666` mWh/1000, avg power `0.0380` W, coverage `95.03%`
### kws/esp32s3

- Status: `OK`
- Runs: `3`
- Repeat coverage: `3` eligible of `3` required
- Partial runs: `0` of `3`; headline basis: `3`

#### Run `019e5d8a-b23b-7c12-a163-1a0d0496eaa9`

- Status: `completed`
- Started: `2026-05-25T05:10:31.227648Z`
- Duration: `76.30 s`
- Iterations: `657` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `106495.0` us, mean `106496.6` us, p95 `106512.0` us, p99 `106518.0` us, stddev `8.1393` us, variance `0.0076%`
- Energy: `0.0087` Wh total, `13.2214` mWh/1000, avg power `0.4441` W, coverage `92.28%`

#### Run `019e653b-a89f-72b2-a648-adc974d864fc`

- Status: `completed`
- Started: `2026-05-26T17:01:09.151405Z`
- Duration: `33.84 s`
- Iterations: `300` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `106495.5` us, mean `106495.8` us, p95 `106511.0` us, p99 `106516.1` us, stddev `8.3175` us, variance `0.0078%`
- Energy: `0.0040` Wh total, `13.1769` mWh/1000, avg power `0.4394` W, coverage `95.72%`

#### Run `019e71e7-8c70-7521-907f-5825a87931ad`

- Status: `completed`
- Started: `2026-05-29T04:04:20.720796Z`
- Duration: `33.87 s`
- Iterations: `300` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `106510.0` us, mean `106512.3` us, p95 `106532.0` us, p99 `106536.2` us, stddev `10.75` us, variance `0.0101%`
- Energy: `0.0040` Wh total, `13.2917` mWh/1000, avg power `0.4427` W, coverage `95.73%`
### kws/pi5

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### kws/jetson

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### kws/m1max

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### kws/modal

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ic/f401re

- Status: `OK`
- Runs: `4`
- Repeat coverage: `4` eligible of `3` required
- Extra eligible runs: `1`
- Coverage warnings: `1 extra eligible run(s) beyond required repeat coverage`
- Partial runs: `0` of `4`; headline basis: `4`

#### Run `019e5db4-e375-7942-9182-e4fef42ce9c7`

- Status: `completed`
- Started: `2026-05-25T05:56:36.341869Z`
- Duration: `75.39 s`
- Iterations: `93` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `755389.0` us, mean `755391.0` us, p95 `755435.2` us, p99 `755441.0` us, stddev `28.76` us, variance `0.0038%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: F401RE/IC 2026-05-25 run predates full-board metered-rail discipline; power is MCU-only scale (~0.071 W average) rather than full-board scale (~0.34 W). Energy excluded; latency remains valid.`

#### Run `019e7598-6637-7dd0-974b-881675b0bedc`

- Status: `completed`
- Started: `2026-05-29T21:16:22.455502Z`
- Duration: `75.59 s`
- Iterations: `93` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `755410.5` us, mean `755416.5` us, p95 `755465.8` us, p99 `755501.1` us, stddev `31.78` us, variance `0.0042%`
- Energy: `0.0066` Wh total, `71.3601` mWh/1000, avg power `0.3412` W, coverage `92.62%`

#### Run `019e759a-52b9-71e0-8769-486b450e2244`

- Status: `completed`
- Started: `2026-05-29T21:18:28.537505Z`
- Duration: `74.07 s`
- Iterations: `93` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `755423.0` us, mean `755418.9` us, p95 `755463.3` us, p99 `755500.3` us, stddev `32.64` us, variance `0.0043%`
- Energy: `0.0066` Wh total, `71.0298` mWh/1000, avg power `0.3394` W, coverage `94.58%`

#### Run `019e75fe-9c3b-7061-9423-2831fac5798d`

- Status: `completed`
- Started: `2026-05-29T23:08:00.956378Z`
- Duration: `74.60 s`
- Iterations: `93` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `755418.0` us, mean `755417.9` us, p95 `755467.2` us, p99 `755492.2` us, stddev `30.57` us, variance `0.0040%`
- Energy: `0.0067` Wh total, `71.5778` mWh/1000, avg power `0.3421` W, coverage `93.91%`
### ic/nano33

- Status: `OK`
- Runs: `4`
- Repeat coverage: `4` eligible of `3` required
- Extra eligible runs: `1`
- Coverage warnings: `1 extra eligible run(s) beyond required repeat coverage`
- Partial runs: `0` of `4`; headline basis: `4`

#### Run `019e5daa-6c50-77d2-a24c-6ff624d22cc5`

- Status: `completed`
- Started: `2026-05-25T05:45:10.480467Z`
- Duration: `74.17 s`
- Iterations: `57` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `1232811.5` us, mean `1232771.1` us, p95 `1233188.1` us, p99 `1233254.1` us, stddev `256.1` us, variance `0.0208%`
- Energy: `0.0008` Wh total, `13.6983` mWh/1000, avg power `0.0398` W, coverage `95.25%`

#### Run `019e674a-f6b6-7092-a5d0-b84111bc0858`

- Status: `completed`
- Started: `2026-05-27T02:37:06.615077Z`
- Duration: `33.75 s`
- Iterations: `26` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `1232612.5` us, mean `1232611.2` us, p95 `1233048.8` us, p99 `1233063.5` us, stddev `383.0` us, variance `0.0311%`
- Energy: `0.0004` Wh total, `13.7165` mWh/1000, avg power `0.0396` W, coverage `96.07%`

#### Run `019e7545-f8a5-75e0-a20d-857ae690429e`

- Status: `completed`
- Started: `2026-05-29T19:46:20.454232Z`
- Duration: `34.23 s`
- Iterations: `26` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `1232334.0` us, mean `1232320.8` us, p95 `1232854.8` us, p99 `1232923.2` us, stddev `336.6` us, variance `0.0273%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: Nano33 session 3 INA219 current path anomaly: ~1 mW average power while latency matched sessions 1-2; energy excluded pending diagnosis.`

#### Run `019e7569-6922-7123-be2a-5478fcbd3e5f`

- Status: `completed`
- Started: `2026-05-29T20:25:03.010607Z`
- Duration: `34.25 s`
- Iterations: `26` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `1232600.0` us, mean `1232580.0` us, p95 `1233090.0` us, p99 `1233226.8` us, stddev `359.9` us, variance `0.0292%`
- Energy: `0.0004` Wh total, `13.6396` mWh/1000, avg power `0.0400` W, coverage `93.28%`
### ic/esp32s3

- Status: `OK`
- Runs: `3`
- Repeat coverage: `3` eligible of `3` required
- Partial runs: `0` of `3`; headline basis: `3`

#### Run `019e5d8c-b9d7-76c1-ad1d-320a29516ca4`

- Status: `completed`
- Started: `2026-05-25T05:12:44.247560Z`
- Duration: `78.03 s`
- Iterations: `128` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `551062.0` us, mean `551062.0` us, p95 `551073.0` us, p99 `551080.0` us, stddev `6.7835` us, variance `0.0012%`
- Energy: `0.0087` Wh total, `67.6314` mWh/1000, avg power `0.4400` W, coverage `90.76%`

#### Run `019e653a-5889-71d1-8252-562d3a20e2e2`

- Status: `completed`
- Started: `2026-05-26T16:59:43.113263Z`
- Duration: `34.71 s`
- Iterations: `59` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `551060.0` us, mean `551061.6` us, p95 `551074.2` us, p99 `551077.2` us, stddev `6.8514` us, variance `0.0012%`
- Energy: `0.0040` Wh total, `67.4158` mWh/1000, avg power `0.4366` W, coverage `94.49%`

#### Run `019e71e6-290e-70a0-a30c-fc3b5f797aba`

- Status: `completed`
- Started: `2026-05-29T04:02:49.742895Z`
- Duration: `34.71 s`
- Iterations: `59` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `551074.5` us, mean `551073.3` us, p95 `551086.0` us, p99 `551087.0` us, stddev `7.8249` us, variance `0.0014%`
- Energy: `0.0040` Wh total, `68.0003` mWh/1000, avg power `0.4404` W, coverage `94.49%`
### ic/pi5

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ic/jetson

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ic/m1max

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ic/modal

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ad/f401re

- Status: `OK`
- Runs: `8`
- Repeat coverage: `3` eligible of `3` required
- Ineligible runs: `5`
- Coverage warnings: `5 run(s) are not eligible for repeat coverage`
- Partial runs: `2` of `8`; headline basis: `3`
- Partial inference windows: `3125`

#### Run `019e5db6-a631-7210-85dd-7cc33f0e0049`

- Status: `completed`
- Started: `2026-05-25T05:58:31.730084Z`
- Duration: `101.5 s`
- Iterations: `8000` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `bme280`
- Partial reasons: `bme280: coverage=0%, threshold=75%, samples=0/100`
- Latency: median `8136.0` us, mean `8136.8` us, p95 `8178.0` us, p99 `8181.0` us, stddev `25.33` us, variance `0.3112%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: F401RE/AD 2026-05-25 partial run predates full-board metered-rail discipline; power is low-boundary scale (~0.071 W average) rather than full-board scale (~0.377 W). Energy excluded; latency remains valid.`; `repeat stats quarantined: F401RE/AD 2026-05-25 run predates full-board metered-rail discipline; excluded from boundary-consistent AD repeat set and published AD averages.`

#### Run `019e5dc5-11f9-7a41-8fd5-543d80de7eaa`

- Status: `completed`
- Started: `2026-05-25T06:14:16.825481Z`
- Duration: `100.9 s`
- Iterations: `8000` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `8136.0` us, mean `8136.8` us, p95 `8178.0` us, p99 `8180.0` us, stddev `25.33` us, variance `0.3113%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: F401RE/AD 2026-05-25 run predates full-board metered-rail discipline; power is low-boundary scale (~0.042 W average) rather than full-board scale (~0.377 W). Energy excluded; latency remains valid.`; `repeat stats quarantined: F401RE/AD 2026-05-25 run predates full-board metered-rail discipline; excluded from boundary-consistent AD repeat set and published AD averages.`

#### Run `019e71d6-2d18-70b2-aef5-0d594ad79a56`

- Status: `completed`
- Started: `2026-05-29T03:45:22.200952Z`
- Duration: `48.86 s`
- Iterations: `3942` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `8138.0` us, mean `8140.0` us, p95 `8181.0` us, p99 `8184.0` us, stddev `25.02` us, variance `0.3074%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`; `repeat stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`

#### Run `019e71dd-d72d-74d1-9087-1efa126593cb`

- Status: `completed`
- Started: `2026-05-29T03:53:44.493501Z`
- Duration: `48.87 s`
- Iterations: `3942` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `8138.0` us, mean `8139.9` us, p95 `8181.0` us, p99 `8184.0` us, stddev `24.94` us, variance `0.3064%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`; `repeat stats quarantined: boundary topology unrecorded; superseded by documented-boundary sessions`

#### Run `019f3675-53cc-7a92-860a-f0e60f02f711`

- Status: `completed`
- Started: `2026-07-06T08:04:46.668663Z`
- Duration: `55.22 s`
- Iterations: `3933` measured, `0` warmup
- Telemetry partial: `True`
- Telemetry partial sources: `ina219`
- Partial reasons: `ina219: coverage=73%, threshold=75%, samples=317/436`
- Partial inference warnings: `3125`
- Latency: median `8136.0` us, mean `8137.4` us, p95 `8179.0` us, p99 `8181.0` us, stddev `25.50` us, variance `0.3134%`
- Energy: `0.0051` Wh total, `1.2980` mWh/1000, avg power `0.3853` W, coverage `86.38%`

#### Run `019f3676-d96e-7f10-9907-3586f4f15606`

- Status: `completed`
- Started: `2026-07-06T08:06:26.414626Z`
- Duration: `52.77 s`
- Iterations: `3942` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `8136.0` us, mean `8137.3` us, p95 `8179.0` us, p99 `8181.0` us, stddev `25.49` us, variance `0.3133%`
- Energy: `0.0051` Wh total, `1.2901` mWh/1000, avg power `0.3827` W, coverage `90.65%`

#### Run `019f3d8d-b3fd-79b2-885f-007399c54367`

- Status: `completed`
- Started: `2026-07-07T17:08:49.616481Z`
- Duration: `48.73 s`
- Iterations: `3943` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `8136.0` us, mean `8137.2` us, p95 `8178.0` us, p99 `8181.0` us, stddev `25.47` us, variance `0.3130%`
- Energy: `0.0052` Wh total, `1.3155` mWh/1000, avg power `0.3894` W, coverage `98.42%`

#### Run `019f43ea-02f5-7ac0-a2c0-e4fd615f9b08`

- Status: `completed`
- Started: `2026-07-08T22:47:21.483171Z`
- Duration: `48.64 s`
- Iterations: `3943` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `8136.0` us, mean `8137.2` us, p95 `8179.0` us, p99 `8181.0` us, stddev `25.48` us, variance `0.3131%`
- Energy: `0.0051` Wh total, `1.2954` mWh/1000, avg power `0.3844` W, coverage `98.35%`
### ad/nano33

- Status: `OK`
- Runs: `4`
- Repeat coverage: `4` eligible of `3` required
- Extra eligible runs: `1`
- Coverage warnings: `1 extra eligible run(s) beyond required repeat coverage`
- Partial runs: `0` of `4`; headline basis: `4`

#### Run `019e5dac-d497-7a52-b3a9-ba11b3f2185f`

- Status: `completed`
- Started: `2026-05-25T05:47:48.247740Z`
- Duration: `106.1 s`
- Iterations: `5636` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `12421.0` us, mean `12422.0` us, p95 `12447.0` us, p99 `12448.0` us, stddev `16.54` us, variance `0.1332%`
- Energy: `0.0011` Wh total, `0.1889` mWh/1000, avg power `0.0370` W, coverage `97.64%`

#### Run `019e6748-d2ff-7271-90c9-fe0415802f39`

- Status: `completed`
- Started: `2026-05-27T02:34:46.399797Z`
- Duration: `49.47 s`
- Iterations: `2576` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `12421.0` us, mean `12422.1` us, p95 `12447.0` us, p99 `12448.0` us, stddev `16.33` us, variance `0.1314%`
- Energy: `0.0005` Wh total, `0.1889` mWh/1000, avg power `0.0369` W, coverage `96.09%`

#### Run `019e7543-37c3-7e32-bd60-339408178788`

- Status: `completed`
- Started: `2026-05-29T19:43:20.003990Z`
- Duration: `49.37 s`
- Iterations: `2577` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `12420.0` us, mean `12416.2` us, p95 `12447.0` us, p99 `12448.0` us, stddev `14.25` us, variance `0.1148%`
- Energy: `unavailable`
- Warnings: `energy stats quarantined: Nano33 session 3 INA219 current path anomaly: ~1 mW average power while latency matched sessions 1-2; energy excluded pending diagnosis.`

#### Run `019e7567-3aea-7621-9671-32874cf4529e`

- Status: `completed`
- Started: `2026-05-29T20:22:40.107209Z`
- Duration: `49.30 s`
- Iterations: `2577` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `12404.0` us, mean `12415.8` us, p95 `12447.0` us, p99 `12448.0` us, stddev `15.56` us, variance `0.1253%`
- Energy: `0.0005` Wh total, `0.1883` mWh/1000, avg power `0.0372` W, coverage `95.23%`
### ad/esp32s3

- Status: `OK`
- Runs: `4`
- Repeat coverage: `3` eligible of `3` required
- Ineligible runs: `1`
- Coverage warnings: `1 run(s) are not eligible for repeat coverage`
- Partial runs: `0` of `4`; headline basis: `4`

#### Run `019e5d8e-c5c3-7fa0-b798-93347e4afa0f`

- Status: `completed`
- Started: `2026-05-25T05:14:58.371730Z`
- Duration: `79.61 s`
- Iterations: `5965` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `11723.0` us, mean `11721.6` us, p95 `11726.0` us, p99 `11727.0` us, stddev `3.4023` us, variance `0.0290%`
- Energy: `0.0086` Wh total, `1.4400` mWh/1000, avg power `0.4248` W, coverage `91.44%`

#### Run `019e6532-b4fd-7310-8cf7-4eda7c26f834`

- Status: `failed`
- Started: `2026-05-26T16:51:22.493732Z`
- Duration: `35.44 s`
- Iterations: `2727` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `11723.0` us, mean `11721.7` us, p95 `11726.0` us, p99 `11727.0` us, stddev `3.5068` us, variance `0.0299%`
- Energy: `0.0000` Wh total, `0.0042` mWh/1000, avg power `0.0012` W, coverage `94.18%`

#### Run `019e6538-f7b8-76a2-b79c-8353623df07c`

- Status: `completed`
- Started: `2026-05-26T16:58:12.792591Z`
- Duration: `35.48 s`
- Iterations: `2727` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `11723.0` us, mean `11721.7` us, p95 `11726.0` us, p99 `11727.0` us, stddev `3.4568` us, variance `0.0295%`
- Energy: `0.0039` Wh total, `1.4288` mWh/1000, avg power `0.4196` W, coverage `94.22%`

#### Run `019e71e4-ab8b-70a3-a4f0-b894ceb098bf`

- Status: `completed`
- Started: `2026-05-29T04:01:12.076407Z`
- Duration: `35.43 s`
- Iterations: `2727` measured, `0` warmup
- Telemetry partial: `False`
- Latency: median `11723.0` us, mean `11721.8` us, p95 `11726.0` us, p99 `11727.0` us, stddev `3.3854` us, variance `0.0289%`
- Energy: `0.0039` Wh total, `1.4382` mWh/1000, avg power `0.4229` W, coverage `94.23%`
### ad/pi5

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ad/jetson

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ad/m1max

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.

### ad/modal

- Status: `NO_DATA`
- Runs: `0`
- Repeat coverage: `0` eligible of `3` required
- Missing repeat runs: `3`
- Coverage warnings: `repeat coverage incomplete: required 3, eligible 0, missing 3`

No runs exported for this cell.


## Outliers

No latency p95 outliers above 2.00x cell median.

## Charts

- Hardware curve: `data/charts/hardware-curve.json`
- Wh comparison: `data/charts/wh-comparison.json`
- Variance illustration: `data/charts/variance-illustration.json`
- Hardware curve (Tier 1): `data/charts/hardware-curve-tier1.json`
- Wh comparison (Tier 1): `data/charts/wh-comparison-tier1.json`
- Variance strip (Tier 1): `data/charts/variance-strip-tier1.json`
