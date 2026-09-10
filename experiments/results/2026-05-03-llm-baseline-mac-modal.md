# Experiment 01: M1 Max + Modal A10G LLM Baseline

Protocol: 5 warmups + 20 persisted measurements per target/tier. Generation uses `temperature=0.0`, `top_p=1.0`, and `seed=42`.

## Latency And Throughput

| Target | Tier | N | p50 ms | p95 ms | p99 ms | p99/p50 | CV | Mean tok/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| m1-max-64gb | long | 20 | 5063.2 | 6020.8 | 6299.1 | 1.24 | 0.082 | 30.44 |
| m1-max-64gb | medium | 20 | 3527.5 | 4128.6 | 4254.8 | 1.21 | 0.071 | 39.97 |
| m1-max-64gb | short | 20 | 1286.0 | 1477.3 | 1494.9 | 1.16 | 0.064 | 37.72 |
| modal-a10g | long | 20 | 1647.5 | 1655.4 | 1657.1 | 1.01 | 0.004 | 97.16 |
| modal-a10g | medium | 20 | 1444.6 | 1503.5 | 1551.0 | 1.07 | 0.025 | 103.24 |
| modal-a10g | short | 20 | 676.8 | 684.7 | 689.2 | 1.02 | 0.008 | 73.83 |

## Methodology Validation

The p99/p50 < 1.4 target held for all measured combinations.

## Thermal Stability

Sustained run `019ded41-fd41-7f12-9c05-b09330b60ccb` recorded 137 inferences. Mean duration changed from 3273.0 ms in the first half to 3781.0 ms in the second half (15.5% change).
Thermal snapshots captured: 49.
Direct macOS thermal-state readings were unavailable on this host; the raw sysctl error is stored with each thermal snapshot.

## Modal Cost

Modal A10 price source: [official Modal pricing page](https://modal.com/pricing), $0.000306/sec.
Recorded billing seconds: 75.41.
Estimated GPU cost: $0.0231.

## Deviations

Completion caps were reduced after the first full local long-tier attempt stalled for more than five minutes. The N=20+5 protocol, three prompt-length tiers, fixed seed, and cross-target model digest assertion remained unchanged.
