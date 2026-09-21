# signal-bench

Open-source benchmarking for TinyML inference on edge devices.

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)

## What it is

signal-bench measures TinyML inference where deployment actually happens: on
small devices, under visible conditions, with the measurement path published
beside the result. It runs reference workloads for keyword spotting, image
classification, and anomaly detection, then records latency, target metadata,
telemetry coverage, energy inputs, and synthesis artifacts.

The point is not to produce a single number and ask you to trust it. The point
is to publish the path that produced the number: adapter contract, telemetry
sources, structured logs, partial-data policy, time-alignment helpers, and
report exports. The methodology is the asset.

At M5, signal-bench is the public tool behind Agoo AI's Signal Reports. It is
ready for mock-target runs, adapter development, telemetry smoke tests, report
generation, and launch-tier MCU reproduction. Post 1 MCU reproduction starts in
[`docs/launch-tier-reproduction.md`](docs/launch-tier-reproduction.md).

## What works today

- ✓ Reference task registry for the three Post 1 workloads: `kws`, `ic`, and
  `ad`.
- ✓ Mock target adapter for no-hardware benchmark dispatch through
  `signal-bench run`.
- ✓ Target adapter contract and MCU USB-CDC base class, with contract tests and
  authoring docs.
- ✓ Telemetry orchestrator with JSON-line structured events, coverage-based
  `telemetry_partial`, and mock INA219/BME280 sources.
- ✓ Synthesis/report CLI that exports matrix YAML, Chart.js data, and markdown
  reports from SQLite benchmark data.
- ✓ Partial-aware aggregation: partial runs are excluded from headline
  statistics and retained in detail output with reasons.
- ✓ FNB58 BLE telemetry source is live-device validated locally; hardware tests
  remain skipped in CI.
- ✓ Real INA219/BME280 I2C telemetry is wired into the launch-tier reproduction
  path, with FNB58 as the wall-side cross-check.
- ✓ Launch-tier hardware-derived energy values are published in the checked-in
  matrices and can be reproduced through the documented MCU path.
- ✓ Launch-tier MCU firmware and a hardware-facing reproduction runner for
  STM32 F401RE, Arduino Nano 33 BLE Sense Rev2, and ESP32-S3 DevKitC are
  included under `src/signal_bench/firmware/launch-tier/` and
  `scripts/run_launch_tier_cell.py`.
- ✗ Cloud GPU, NPU, and accelerator targets are not supported in the public CLI.
- ✗ The package is not published on PyPI yet; use a source checkout.

## 15-minute quickstart

The no-hardware smoke path exercises the telemetry orchestrator with mock
sources and writes a temporary SQLite database:

```bash
git clone https://github.com/narteyb/signal-bench
cd signal-bench
uv sync --extra dev
uv run signal-bench telemetry test --db /tmp/signal-bench-quickstart.db --duration 5 --no-fnb58 --quiet
```

Expected shape:

```text
{"event":"run_started", ... "source":"orchestrator"}
{"event":"source_started", ... "source":"mock_ina219_main"}
{"event":"source_started", ... "source":"mock_bme280_lab"}
...
{"event":"telemetry_partial_decided", ... "partial":false}
{"event":"run_completed", ... "samples_written":...}

Telemetry Test Summary
Source             Samples   Rows   Rate (Hz)   Status
mock_ina219_main   ...       ...    ...         OK
mock_bme280_lab    ...       ...    ...         OK
telemetry_partial: False
Skipped sources: fnb58
```

To prove the benchmark dispatch path without hardware:

```bash
uv run signal-bench list-tasks
uv run signal-bench run --task kws --target mock --runs 20 --corpus X
```

That is the first benchmark path for a new contributor: source checkout,
dependency sync, telemetry smoke test, task listing, and one mock-target run.
It should complete in less than 15 minutes on a normal development machine.

## Verify Post 1 Without Hardware

The launch-tier raw telemetry is published as a Hugging Face dataset:
`narteybrown/signal-bench-post1-telemetry-v1`, pinned at revision
`08986c51ccb57c681a616524b10be31e7dd0d901`. The bundle is anonymous-read:
no Hugging Face account or token is required.

From a clean checkout, this one command fetches the pinned bundle, regenerates
the Post 1 matrix from the raw SQLite rows, regenerates the launch-tier
acceptance bands from the same data, and compares representative published
figures against the checked-in launch artifacts:

```bash
uv run python scripts/verify_post1_from_bundle.py
```

Expected proof points include:

```text
Post 1 no-hardware verification succeeded.
| published median latency | kws/f401re | - | 158.926 | 158.926 |
| published mWh/1000 figure | kws/nano33 | - | 2.366554372571872 | 2.366554372571872 |
| published variance figure | ad/f401re | 019f3676-d96e-7f10-9907-3586f4f15606 | 0.313283690900598 | 0.313283690900598 |
```

Generated files are written under `.signal-bench-data/post1/`, which is ignored
by git. To look up the raw artifact and row counts for a published run ID:

```bash
uv run python scripts/verify_post1_from_bundle.py \
  --run-id 019e5da7-ef3e-7830-94a8-2ef6f6845b8e
```

The working databases under `data/*.db` are intentionally not committed. Public
verification fetches the pinned Hugging Face bundle instead of relying on local
database state.

## How it works

Targets are isolated behind the adapter contract. The harness asks an adapter
to prepare a target, warm it up, stream ordered inference results, report
target metadata, and tear down cleanly. New target support starts in
[`docs/writing-an-adapter.md`](docs/writing-an-adapter.md).

Telemetry runs beside the target. The orchestrator starts sources, fans grouped
samples into scalar rows, writes through one queue, and emits structured
JSON-line events when sources lag, drop, or recover. Hardware setup starts in
[`docs/telemetry-setup.md`](docs/telemetry-setup.md); log inspection is covered
in [`docs/telemetry/observability.md`](docs/telemetry/observability.md).

Synthesis turns SQLite runs into the artifacts used by Signal Reports: matrix
YAML, Chart.js-ready data, and markdown summaries. Partial runs stay visible in
detail output, but they do not drive headline medians or variance bands. If the
conditions are missing, the number is not a benchmark.

The architecture overview is in [`docs/architecture.md`](docs/architecture.md).
Hardware support status is tracked in
[`docs/hardware-compatibility.md`](docs/hardware-compatibility.md).

## Schema overview

signal-bench stores run data in SQLite through SQLAlchemy models in
`src/signal_bench/schema.py`.

| Table | Purpose |
|---|---|
| `targets` | Device or runtime identity: board name, kind, CPU, accelerator, memory, OS, and extra metadata. |
| `tasks` | Benchmark workload identity: task name, version, family, and protocol YAML provenance. |
| `runs` | One benchmark attempt for one target and one task, including corpus tag, runtime/model metadata, telemetry partial flags, and status. |
| `results` | Per-inference measurements: sequence, start timestamp, duration, throughput, accuracy proxy, Wh/inference, and extra metadata. |
| `telemetry_samples` | Scalar telemetry rows keyed by run, timestamp, source, metric, and value. Grouped source samples are expanded here for analysis. |
| `failures` | Structured records for cells that cannot produce valid runs, such as memory-fit failures or toolchain errors. |

The schema is deliberately provenance-heavy. A published result should be
traceable back to the target, task, model lineage, runtime, telemetry coverage,
and failure policy that shaped it.

## Reproducibility

Reproducibility in signal-bench means the setup is inspectable, not just that a
number is printed twice. The public artifacts include:

- adapter lifecycle contracts and target metadata requirements;
- telemetry setup notes and source-specific partial-data policy;
- structured JSON-line telemetry health events;
- pinned public telemetry rows for runs, results, telemetry samples, and failures;
- synthesis outputs that exclude `telemetry_partial=true` runs from headline
  statistics while keeping them visible in detail reports.

Hardware runs must document the power boundary. MCU rows use rail-side INA219
by default. SBC rows use whole-board input power when available. Laptop and
cloud rows use package-power counters and must be labeled as such.

## CLI overview

- `uv run signal-bench init` — create or migrate the SQLite database.
- `uv run signal-bench list-tasks` — list the reference workloads available to
  `uv run signal-bench run`.
- `uv run signal-bench run --task kws --target mock --runs 20 --corpus X` — run a
  benchmark task against the mock target.
- `uv run signal-bench telemetry sources` — show configured telemetry sources and
  availability.
- `uv run signal-bench telemetry test --duration 5 --no-fnb58` — smoke-test telemetry
  with mock sources.
- `uv run signal-bench synth report` — export matrix YAML, chart JSON, and a markdown
  synthesis report.

Run `uv run signal-bench <command> --help` for exact flags and exit codes.

## Documentation

| Need | Start here |
|---|---|
| Write a target adapter | [`docs/writing-an-adapter.md`](docs/writing-an-adapter.md) |
| Wire telemetry hardware | [`docs/telemetry-setup.md`](docs/telemetry-setup.md) |
| Reproduce a Post 1 MCU cell | [`docs/launch-tier-reproduction.md`](docs/launch-tier-reproduction.md) |
| Interpret launch-tier acceptance bands | [`docs/launch-tier-acceptance-bands.md`](docs/launch-tier-acceptance-bands.md) |
| Check hardware support | [`docs/hardware-compatibility.md`](docs/hardware-compatibility.md) |
| Understand the architecture | [`docs/architecture.md`](docs/architecture.md) |
| Read structured logs | [`docs/telemetry/observability.md`](docs/telemetry/observability.md) |
| Understand report exports | [`docs/synth-report-spec.md`](docs/synth-report-spec.md) |
| Inspect methodology specs | [`docs/methodology.md`](docs/methodology.md) |
| Read design decisions | [`docs/adr/`](docs/adr/) |

## Contributing

We welcome contributions that make measurements more reproducible: new target
adapters, tighter telemetry sources, better synthesis checks, and clearer docs.
Start with [CONTRIBUTING.md](CONTRIBUTING.md), then use the adapter guide if
you are adding hardware support.

## License

signal-bench is licensed under the [Apache License 2.0](LICENSE). See
[NOTICE](NOTICE) for required third-party attributions covering the
MLPerf Tiny reference models included under `models/reference/`, and see
[`docs/third-party-data.md`](docs/third-party-data.md) for the benchmark-input
dataset inventory. The KWS MCU subset is redistributed under CC BY 4.0, not
Apache-2.0; IC and AD subsets are regenerated from upstream rather than
redistributed in this repository.

## Acknowledgments

signal-bench's reference workloads are in conversation with MLPerf Tiny, the
TinyML community, Edge Impulse's public benchmarking work, and the practical
edge-AI tooling built by open hardware maintainers.

---

signal-bench is developed by [Agoo AI](https://agoo-ai.com).
