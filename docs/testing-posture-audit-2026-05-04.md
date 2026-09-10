# Testing Posture Audit - 2026-05-04

This audit backfills the Testing Posture invariants INV-09 through INV-13 against the
codebase at E01 (`af0afca`). The local environment date during the work was
2026-05-03; the audit filename follows the testing-posture decision date requested
for this session.

## Interpretations

- `tools/check_test_coverage.py` enforces Python source counterparts mechanically and
  reports non-Python or marker-only files through `tests.conftest.KNOWN_NON_TEST_FILES`.
- Firmware files from M3a remain compile-verified, not pytest-verified, until M3 proper
  adds firmware-build CI. They are acknowledged as known non-test files.
- Experiment helper modules under `experiments/lib/` are covered by the E01 smoke and
  reproducibility tests because they are not public library surface.
- E01 reproducibility fixtures freeze the 2026-05-03 headline numbers and replay the
  recorded Ollama/Modal measurement data without network or GPU access.

## Summary

- Files audited under `src/`, `src/signal_bench_cli/`, `experiments/`, and migrations: 39
- Enforced source files: 19
- Known non-test files: 20
- Initial missing counterpart categories: 10
- Gaps closed in this session: 10

## INV-09 Compliance Matrix

| File | Category | Required tests | Present after backfill | Initial missing |
|---|---|---|---|---|
| `src/signal_bench/__init__.py` | known non-test | version coverage | `tests/e2e/test_main_subprocess.py` | deterministic acknowledgement |
| `src/signal_bench/ids.py` | core module | unit | `tests/unit/test_ids.py` | - |
| `src/signal_bench/schema.py` | core module | unit | `tests/unit/test_schema.py` | - |
| `src/signal_bench/telemetry/__init__.py` | known non-test | re-export marker | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/telemetry/base.py` | core module | unit | `tests/unit/telemetry/test_base.py` | deterministic path |
| `src/signal_bench/telemetry/collector.py` | core module | unit | `tests/unit/telemetry/test_collector.py` | deterministic path |
| `src/signal_bench/telemetry/mock.py` | mock impl | unit + spec-fidelity | `tests/unit/telemetry/test_mock.py`, `tests/spec_fidelity/telemetry/test_mock_fidelity.py` | deterministic path + spec-fidelity |
| `src/signal_bench/migrations/env.py` | known non-test | migration wiring | `KNOWN_NON_TEST_FILES`, migration tests | deterministic acknowledgement |
| `src/signal_bench/migrations/script.py.mako` | known non-test | Alembic template | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/migrations/versions/0001_initial_schema.py` | migration | roundtrip | `tests/migrations/test_initial_schema_roundtrip.py` | generalized roundtrip |
| `src/signal_bench/migrations/versions/0002_add_telemetry_partial_flag_to_runs.py` | migration | roundtrip | `tests/migrations/test_add_telemetry_partial_flag_to_runs_roundtrip.py` | generalized roundtrip |
| `src/signal_bench/firmware/__init__.py` | known non-test | marker only | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/firmware/esp32-s3-wake-word/.gitignore` | known non-test | firmware metadata | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/firmware/esp32-s3-wake-word/README.md` | known non-test | firmware docs | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/firmware/esp32-s3-wake-word/main/CMakeLists.txt` | known non-test | firmware metadata | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/firmware/esp32-s3-wake-word/main/idf_component.yml` | known non-test | firmware metadata | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/firmware/esp32-s3-wake-word/main/main.c` | known non-test | compile verification | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/firmware/esp32-s3-wake-word/platformio.ini` | known non-test | firmware metadata | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench/firmware/esp32-s3-wake-word/sdkconfig.defaults` | known non-test | firmware metadata | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench_cli/__init__.py` | known non-test | marker only | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench_cli/__main__.py` | CLI entry point | subprocess E2E | `tests/e2e/test_main_subprocess.py` | subprocess E2E |
| `src/signal_bench_cli/commands/__init__.py` | known non-test | marker only | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `src/signal_bench_cli/commands/init.py` | CLI command | CliRunner + subprocess E2E | `tests/integration/test_init_command.py`, `tests/e2e/test_init_subprocess.py` | subprocess E2E |
| `src/signal_bench_cli/commands/telemetry.py` | CLI command | CliRunner + subprocess E2E | `tests/integration/test_telemetry_command.py`, `tests/e2e/test_telemetry_subprocess.py` | deterministic path + subprocess E2E |
| `experiments/README.md` | known non-test | workspace docs | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `experiments/__init__.py` | known non-test | marker only | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `experiments/configs/llm-baseline-nemoclaw.yaml` | known non-test | task fixture data | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `experiments/results/.gitkeep` | known non-test | marker only | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `experiments/results/2026-05-03-llm-baseline-mac-modal.md` | known non-test | committed result artifact | `KNOWN_NON_TEST_FILES` | deterministic acknowledgement |
| `experiments/e01_llm_baseline/__init__.py` | experiment | smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/e01_llm_baseline/__main__.py` | experiment | smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/e01_llm_baseline/analysis.py` | experiment | smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/e01_llm_baseline/prompts.py` | experiment | smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/e01_llm_baseline/run.py` | experiment | smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/lib/__init__.py` | experiment support | E01 smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/lib/measurement.py` | experiment support | E01 smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/lib/modal_client.py` | experiment support | E01 smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/lib/ollama_client.py` | experiment support | E01 smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |
| `experiments/lib/schema_writer.py` | experiment support | E01 smoke + reproducibility | `tests/experiments/test_e01_llm_baseline_smoke.py`, `tests/experiments/test_e01_llm_baseline_reproducibility.py` | smoke + reproducibility |

## Enforcement Check

Passing output:

```text
INV-09 test coverage check passed (19 source files enforced).
```

Artificial gap output, verified by temporarily removing
`tests/spec_fidelity/telemetry/test_mock_fidelity.py`:

```text
INV-09 test coverage check failed.

Missing required tests:
  - src/signal_bench/telemetry/mock.py [mock impl] -> tests/spec_fidelity/telemetry/test_mock_fidelity.py
```
