# signal-bench Experiments

This directory contains research workflows that produce data and validate methodology. It is
intentionally separate from `src/signal_bench/`: experiments may import the core library and write
standard schema rows, but the library never imports experiment code.

## Experiment 01

`experiments/e01_llm_baseline` measures the local M1 Max Ollama ceiling and the Modal A10G ceiling
with the same Ollama model tag and the N=20+5 protocol.

Install experiment-only dependencies:

```sh
uv sync --extra dev --extra experiments
```

Run from the repo root:

```sh
uv run --extra experiments python -m experiments.e01_llm_baseline
```

The orchestrator writes `Target`, `Task`, `Run`, and `Result` rows into `signal-bench.db`, then
renders a Markdown findings summary under `experiments/results/` and updates
`docs/methodology.md`.
