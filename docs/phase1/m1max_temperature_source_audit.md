# M1 Max Temperature Source Audit

Date: 2026-06-16

## Purpose

The Phase 1 M1 Max canonical brief requires CPU die and GPU die temperature at
the start and end of every run, with an 85 C exclusion gate. The prescribed
source was `powermetrics --samplers thermal`.

This audit records what the M1 Max host actually exposes.

## Host State

- Target: M1 Max MacBook Pro 64GB (`MacBookPro18,2`)
- Runtime: Ollama `0.30.7`
- Model: `qwen2.5:7b`
- Model digest: `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`
- Power: AC attached
- Low Power Mode: off (`powermode 0`)

## Findings

### `powermetrics --samplers thermal`

Command:

```bash
sudo powermetrics --samplers thermal -n 1 -i 1000
```

Observed output includes thermal pressure only:

```text
**** Thermal pressure ****

Current pressure level: Nominal
```

It does not include CPU die temperature or GPU die temperature on this host.

### `powermetrics --samplers all --show-extra-power-info`

Command:

```bash
sudo powermetrics --samplers all --show-extra-power-info -n 1 -i 1000
```

Observed output includes CPU/GPU/ANE power estimates and thermal pressure:

```text
CPU Power: 3562 mW
GPU Power: 106 mW
ANE Power: 0 mW
Combined Power (CPU + GPU + ANE): 3669 mW

**** Thermal pressure ****

Current pressure level: Nominal
```

It still does not include CPU die temperature or GPU die temperature. The power
values are retained as supplementary estimates only; they are not
measurement-grade energy for Phase 1.

### `ioreg`

Command:

```bash
ioreg -r -c AppleARMPMUTempSensor -l
```

Observed result: Apple PMU temperature sensor objects exist, with product labels
such as `PMU tdev1`, but the CLI-visible properties do not include Celsius
temperature values.

## Consequence

The M1 Max canonical run was initially blocked under the Celsius-temperature
methodology because CPU/GPU die-temperature fields are not available from the
prescribed `powermetrics` source on this machine and macOS build.

This was resolved by the Tech Lead decision on 2026-06-16: for Apple Silicon,
`powermetrics` thermal pressure is the platform-specific thermal gate. The M1
runner now records thermal pressure level at run start and end, and aborts or
excludes runs whose end pressure is `>=2` (`heavy` or worse).

## Options For Tech Lead Decision

Decision taken: option 2. The protocol is documented in
`docs/phase1/measurement_protocol.md`, and the canonical M1 Max artifact is
`data/phase1/m1max/canonical/phase1-m1max-canonical-20260617T000709Z/phase1-m1max-canonical-report.md`.
