# CLI Audit Results — A07

Source draft:
`<local-path> Drive/Downloads/Agoo AI Project Files/Post_1_TinyML_Reality_Check_Draft_v01.md`

Fresh environment:
`/tmp/signal-bench-audit-env`

Local install command:
`python -m pip install -e .`

Clean clone check:
`git clone <local-path> /tmp/signal-bench-clone && pip install -e . && signal-bench --help`

Result: PASS. The `signal-bench` entry point is accessible after editable install from a clean clone.

## Commands from Draft

### pip install signal-bench
Status: PASS
Error: n/a
Fix: No syntax fix required. For the pre-PyPI/public-source path, the draft was updated to a source checkout plus `pip install -e .`, matching the release runbook and clean-clone verification.
Post draft line: "Install signal-bench"

### signal-bench run --target esp32s3 --task kws --n 20 --warmup 5
Status: FAIL
Error: `Error: No such option '--n'. Did you mean '--runs'?`
Fix: Use `--runs` instead of `--n`; add required `--corpus X`. The current public CLI supports the `mock` target only unless an adapter factory is injected, so the post draft was changed to the no-hardware smoke command `signal-bench run --target mock --task kws --runs 20 --corpus X`.
Post draft line: "Run keyword spotting on a connected ESP32-S3"

### signal-bench run --target mcu-matrix --task all --n 20 --warmup 5
Status: FAIL
Error: `Error: No such option '--n'. Did you mean '--runs'?`
Fix: There is no `mcu-matrix` target, no `all` task, and no `--warmup` flag in the current CLI. The post draft was changed to CLI-verifiable commands: `signal-bench list-tasks` and `signal-bench run --target mock --task kws --runs 20 --corpus X`.
Post draft line: "Run the full MCU matrix"

### signal-bench synth report --format markdown
Status: FAIL
Error: `Error: No such option '--format'.`
Fix: `synth report` renders markdown by default via `--output-report`; there is no `--format` flag. The syntax-verified replacement is `signal-bench synth report --db signal-bench.db --quiet`.
Post draft line: "Export results to markdown"

## Corrected Commands Verified

### signal-bench --help
Status: PASS
Error: n/a
Fix: n/a
Post draft line: source checkout verification

### signal-bench list-tasks
Status: PASS
Error: n/a
Fix: n/a
Post draft line: list supported workloads

### signal-bench run --db /tmp/signal-bench-audit-db.sqlite --target mock --task kws --runs 20 --corpus X
Status: PASS
Error: n/a
Fix: n/a
Post draft line: no-hardware CLI smoke benchmark

### signal-bench telemetry test --db /tmp/signal-bench-audit-telemetry.sqlite --duration 1 --no-fnb58 --quiet
Status: PASS
Error: n/a
Fix: n/a
Post draft line: telemetry smoke test

### signal-bench synth report --db /tmp/signal-bench-audit-db.sqlite --skip-charts --skip-report --quiet
Status: PASS
Error: n/a
Fix: n/a
Post draft line: report-export syntax check

## Hardware Follow-Up

The public CLI currently smoke-tests `mock` through `signal-bench run`. The accepted MCU matrix used `scripts/run_p3_mcu_matrix.py` and live hardware. A human tester should verify the published hardware reproduction path once the public-facing MCU adapter/matrix command is exposed.
