# Synth Report CLI Spec

T3.6 adds `signal-bench synth report`, the command that composes the full T3
pipeline. It reads a matrix config, queries the benchmark SQLite database,
writes matrix-data YAML, prepares Chart.js JSON, and renders a markdown report.
The command is read-only with respect to the database.

## Command

```bash
signal-bench synth report \
  --matrix-config configs/matrix.yaml \
  --db signal-bench.db \
  --output-yaml data/matrices/post-1-data.yml \
  --output-charts data/charts \
  --output-report data/reports/post-1-report.md
```

`--skip-charts` suppresses Chart.js JSON generation. `--skip-report` suppresses
markdown rendering. `--quiet` hides stage-by-stage progress but still prints the
final status summary. `--outlier-threshold` controls the report section that
flags runs whose latency p95 exceeds a multiple of the cell median.

## Pipeline

Stage 1 loads and validates `MatrixConfig`. Stage 2 opens the SQLite database.
Stage 3 calls T3.4's `export_matrix()` to produce schema-versioned matrix YAML.
Stage 4 calls T3.5's `write_chart_json_files()` unless skipped. Stage 5 calls
`render_markdown_report()` unless skipped. Each stage has a clear output path so
T4 can consume artifacts without querying SQLite.

The command intentionally does not run Alembic migrations or create schema. It
expects the benchmark database to already exist, matching the rest of the
synthesis tooling's read-only posture. Phase 5 and earlier run commands own DB
creation and measurement writes.

## Markdown Report

The markdown report starts with matrix name, generation timestamp, cell count,
run count, and status counts. The summary table shows one row per task and one
column per target, with status, median latency, and mWh/1000 inferences in each
cell. Per-cell detail follows with run count, telemetry status, latency stats,
energy stats, and warnings. The outlier section lists runs whose p95 tail
exceeds the configured threshold. The final section references the three chart
JSON files.

## Status Semantics

`OK` means every run completed with full telemetry. `PARTIAL` means at least one
run has `telemetry_partial=true`. `INCOMPLETE` means at least one run has no
`finished_at` timestamp or non-completed status. `NO_DATA` means the configured
cell has no matching runs. Cell status uses the worst status present.

## Exit Codes

`0` means clean success. `1` means the pipeline completed but partial or
incomplete cells were present. `2` is an internal pipeline failure. `3` is a
configuration or path error. `4` is a database access or query error. Error
messages include the relevant path and a short remediation hint where useful.

## Examples

For local development with a temporary database:

```bash
signal-bench synth report --db /tmp/signal-bench.db --quiet
```

To regenerate only matrix YAML while leaving existing chart and markdown files
untouched:

```bash
signal-bench synth report --skip-charts --skip-report
```

To inspect tail behavior more aggressively, lower the outlier threshold:

```bash
signal-bench synth report --outlier-threshold 1.5
```
