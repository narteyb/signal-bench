# Phase 5 Measurement Protocol

This document is the repo-local operational form of the Phase 5 measurement
protocol. It is additive to the existing signal-bench decisions: the adapter
contract remains narrow per AD-01 and AD-02, telemetry capture remains a
separate lifecycle per AD-03, structured logging follows AD-04, partial-data
decisions follow AD-05, timing attribution follows AD-06, and headline
aggregation policy follows AD-07.

The implementation lives in `signal_bench.orchestrator`. The CLI is a wrapper:
`signal-bench run` parses flags, builds an orchestrator config, and delegates
the cell lifecycle to library code.

## P-01: Corpus Tagging

Every successful row in `runs` has a first-class `corpus_tag`. Allowed database
values are `X`, `N1`, `N2`, `N3`, and `N4`; `N2` is reserved for forward
compatibility and is not active in the current CLI campaign surface.

The tag is supplied explicitly through `signal-bench run --corpus`. There is no
runtime default. Legacy rows from before this protocol are migrated to
`corpus_tag = "X"` and marked with `extra.pre_protocol = true`, so they remain
auditable instead of being silently reclassified.

## P-02: Parallel Collection Ordering

Hardware that does not contend may run cells independently. When two planned
cells share the same target, the orchestrator applies task-level block
randomization and records the seed in `Run.extra.batch_seed`.

When the next same-target cell crosses corpus boundaries, the orchestrator waits
for the device to return within 2 degrees C of the prior cell's starting
temperature. The starting temperature is read through the adapter
`read_thermal()` contract and recorded in `Run.extra.device_thermal.start`.
If the target has no device-temperature source, the orchestrator takes an
auditable fallback path: ambient-relative wait when a BME280 ambient baseline is
configured, otherwise a bounded fixed wait. The selected path is recorded in
`Run.extra.cooldown`, with flags in `Run.extra.thermal_gate_flags`.

## P-03: N1 Cross-Instance Discipline

`Target.target_id` remains a generated UUID. The physical unit convention lives
in `Target.name`: examples include `pi5-8gb-001`, `pi5-8gb-002`, and
`nucleo-f401re-001`.

N1 cells enforce a cold-start idle interval before warmup and record it in
`Run.extra.coldstart`. Ambient parity is enforced with the real BME280 ambient
source when no test reader is injected. If ambient is outside tolerance, the
orchestrator waits up to the configured maximum and then proceeds with
`coldstart_drift` in `Run.extra.thermal_gate_flags`; it does not block
indefinitely.

## P-04: N3 Model Invocation Pattern

N3 accuracy floors live in `src/signal_bench/protocols/n3.yaml`:

```yaml
n3_accuracy_floors:
  kws:
    metric: top1
    floor_delta_pp: -2.0
  ic:
    metric: top1
    floor_delta_pp: -1.5
    floor_sparsity: 0.40
  ad:
    metric: auroc
    floor_ratio: 0.97
```

`signal-bench run --corpus N3` requires `--model-lineage path/to/lineage.json`.
The same flag is rejected for every non-N3 corpus, because silently ignoring a
lineage file would hide configuration mistakes.

Accepted N3 cells store the parsed payload at `Run.extra.model_lineage`. A
variant below the configured floor writes no `runs` row; it writes a `failures`
row with `failure_mode = "accuracy_gate_rejected"` and stores the lineage payload
in `Failure.context`. This preserves the audit split: the floor enforced comes
from protocol config, while the variant's claim comes from the lineage file.

## P-05: N4 Failure Documentation

Failed cells are first-class data in the `failures` table, not partial rows in
`runs`. Initial failure modes are:

- `activation_memory_overflow`
- `flash_memory_overflow`
- `quantization_conversion_error`
- `toolchain_version_skew`
- `accuracy_gate_rejected`

The table also stores `diagnostic_signature`, `toolchain_versions`, optional
`error_log_uri`, and structured `context` for mode-specific payloads.

## P-06: Reproducibility Evidence Archive

At cell start the orchestrator creates `data/archives/<run_id>/` and records the
path in `Run.extra.archive_path`. Archive helpers write the toolchain manifest,
orchestrator log slices, and the N3 lineage payload when present.

The archive is local during measurement. Public archive publication and nightly
remote sync are release operations outside this repo-local implementation.

## P-07: Operational Checklist

Before a session, confirm the database commit, target registration, telemetry
source status, and ambient conditions. Per cell, confirm `--corpus`, confirm
`--model-lineage` for N3, run the cell, and verify either a successful `runs`
row or a first-class `failures` row.

After a session, use:

```bash
signal-bench inspect --session 2026-05-18
signal-bench inspect --session 2026-05-18 --failures
```

The inspect command is deliberately narrow. It supports `--session`, `--corpus`,
`--target`, `--task`, and `--failures` for Phase 5 review only; synthesis and
reporting remain separate surfaces.
