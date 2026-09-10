# Architecture

signal-bench is organized around four boundaries:

1. **Task registry.** Reference workloads describe what is being measured:
   keyword spotting (`kws`), image classification (`ic`), and anomaly detection
   (`ad`). Task metadata points to model artifacts, input data, and lineage.
2. **Target adapters.** Adapters own device-specific setup and inference. The
   harness owns run lifecycle, persistence, telemetry coordination, and failure
   policy. See `docs/writing-an-adapter.md`.
3. **Telemetry sources.** Sources emit grouped samples with metric/value
   payloads. The telemetry orchestrator expands those groups into persisted
   rows, logs source health, and decides `telemetry_partial`.
4. **Synthesis.** Report builders aggregate complete runs into matrix YAML,
   Chart.js JSON, and markdown summaries. Partial runs remain visible but do
   not drive headline numbers.

The design goal is reproducible measurement rather than broad device support at
any cost. A benchmark row must carry enough context to explain the target,
runtime, model, telemetry coverage, and power boundary that produced it.

## Core data flow

```text
TaskSpec + AdapterConfig
  -> adapter.prepare(run_id)
  -> telemetry_orchestrator.start_run(run_id)
  -> adapter.warmup()
  -> adapter.measure(task, iterations)
  -> results + telemetry_samples
  -> synthesis/report export
```

Adapters do not write database rows directly. Telemetry sources do not know
which task is running. Synthesis does not infer missing provenance. Each layer
has one job and a typed interface to the next layer.

## Public-release scope

The M5 public release supports mock-target runs, adapter development,
telemetry smoke tests, report generation, and the documentation needed to audit
the Signal Report methodology. Hardware compatibility status is tracked in
`docs/hardware-compatibility.md`.

## Design records

The detailed design decisions live in `docs/adr/`:

- AD-01: adapter contract
- AD-02: MCU adapter base
- AD-03: telemetry orchestrator
- AD-04: structured telemetry logging
- AD-05: partial-data policy
- AD-06: telemetry time alignment
- AD-07: partial-aware headline aggregation
