# Matrix Config Schema

`configs/matrix.yaml` defines the planned Post 1 benchmark matrix. It is a
static plan: it says which task-target cells Phase 5 should attempt and what
values should be treated as expectations in reporting. It does not store
measurement data, adapter wiring, telemetry sources, or metric formulas.

## Top-Level Fields

- `schema_version`: integer schema version. T3.1 ships version `1`.
- `name`, `version`, `description`, `created`: human-readable matrix metadata.
- `tasks`: non-empty list of registered task names. For Post 1 this is
  `kws`, `ic`, and `ad`.
- `targets`: non-empty list of target adapter names. Post 1 uses seven targets:
  `f401re`, `nano33`, `esp32s3`, `pi5`, `jetson`, `m1max`, and `modal`.
- `defaults`: default execution expectations inherited by cells unless a cell
  overrides them.
- `cells`: explicit list of included `(task, target)` matrix cells.
- `exclusions`: explicit list of skipped cells with reasons. Post 1 has none.
- `phase_5_overrides`: optional hints for Phase 5 implementation details.

The Post 1 config intentionally lists 21 cells, not 18. Earlier planning text
sometimes described "six targets," but the concrete target roster contains
seven execution environments: three MCUs, Pi 5, Jetson Orin Nano, M1 Max, and
Modal A10G. The schema does not infer cells from `tasks x targets`; every cell
is explicit so future reports can alter, annotate, or remove individual cells
without changing the loader contract.

## Defaults And Cells

`defaults.iterations` is the planned measured inference count per cell and must
be positive. `defaults.warmup_iterations` must be zero or positive. Budget
fields are optional and informational: `accuracy_threshold` is a float in
`[0, 1]`, `latency_budget_ms` is milliseconds per inference, and
`energy_budget_uwh` is micro-watt-hours per inference. T3.1 does not make these
hard pass/fail gates; later synthesis modules use them to flag deviations.

Each cell must include `task` and `target`. It may override `iterations`,
`warmup_iterations`, `accuracy_threshold`, `latency_budget_ms`,
`energy_budget_uwh`, and `notes`. Duplicate cells are invalid. A cell cannot
also appear in `exclusions`.

## Validation

`signal_bench.synth.matrix_config.load_matrix_config()` validates structure and
cross-references. Every task must exist in `signal_bench.tasks`, every target
must be in the known target-name set, every cell must reference a declared task
and target, and all `(task, target)` pairs must be unique. Schema versions other
than `1` fail fast so future matrix formats can evolve deliberately.

## Phase 5 Overrides

Overrides are advisory. Post 1 currently includes only `ic.f401re`, preserving
T2.5's finding that this is the closest SRAM cell. Phase 5 may use that hint
when selecting a tensor arena size, but the matrix remains the benchmark plan,
not a hardware tuning file. Hardware-specific details such as serial ports,
clock settings, power rails, telemetry source selection, and execution order
belong to adapters and orchestrators. Keeping those details out of the matrix
lets the same benchmark plan survive adapter implementation changes.
