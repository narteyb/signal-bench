# Contributing to signal-bench

signal-bench accepts contributions that make edge inference measurements more
reproducible. The highest-value changes are target adapters, telemetry sources,
synthesis checks, and documentation that makes the measurement path easier to
audit.

## Before you start: the CLA

signal-bench requires contributors to sign a Contributor License Agreement
through Linux Foundation EasyCLA before a pull request can merge. Your first PR
will trigger the EasyCLA check. If you have not signed yet, the check links you
to the EasyCLA web flow; after you sign, the check re-runs and later PRs from
the same identity are cleared automatically.

The CLA keeps IP provenance clear for an Apache 2.0 project. No CLA means no
merge, even for small patches.

The agreement text is in [`CLA.md`](CLA.md). It is an Apache 2.0-compatible
individual CLA used to confirm that contributions can be distributed as part of
signal-bench.

The project-specific EasyCLA signing URL is pending maintainer activation in
the Linux Foundation Project Control Center. Until that activation is complete,
contributors should rely on the EasyCLA link attached to their first pull
request. The manual Linux Foundation setup steps are listed in
[`docs/easycla-setup.md`](docs/easycla-setup.md).

## Development setup

Use a source checkout until the package is published:

```sh
git clone https://github.com/narteyb/signal-bench
cd signal-bench
uv sync --extra dev
uv run pre-commit run --all-files
uv run pytest
```

For CLI smoke checks without hardware:

```sh
uv run signal-bench telemetry test --duration 5 --no-fnb58 --quiet
uv run signal-bench run --task kws --target mock --runs 20
```

## Unpublished analysis work

Generated analysis, findings, specifications, and any material describing
unpublished work are written to `~/Downloads/signal-bench-working/`, outside
the repository. They enter the repository only after Dan has reviewed and
approved them for publication. Commit guidance for code and already-approved
publication material does not authorize committing unreviewed analysis output.

## What to contribute

- **Target adapters.** New device-under-test support starts in
  [`docs/writing-an-adapter.md`](docs/writing-an-adapter.md). This is the most
  useful contribution path for new MCUs or board variants.
- **Telemetry sources.** Start with [`docs/telemetry-setup.md`](docs/telemetry-setup.md)
  and AD-03. A dedicated telemetry-source authoring guide is planned but not
  required for small telemetry fixes.
- **Methodology changes.** Open an issue before coding. Changes to partial-data
  policy, aggregation, timing, or headline metrics need design review.
- **Documentation fixes.** Small, specific documentation PRs are welcome. Keep
  docs operational and cite the code or command they describe.

## Code style

Type hints are required for new production code. Ruff, Black, mypy, and
pre-commit must pass. New behavior needs tests in the matching test layer:
unit tests for library code, integration tests for CLI/database behavior, and
spec-fidelity tests for contract promises.

signal-bench treats tests as part of the architecture. CI runs
`tools/check_test_coverage.py` before pytest, so new source files need the
counterpart tests required by INV-09 or an explicit entry in
`tests.conftest.KNOWN_NON_TEST_FILES`.

## PR process

1. Fork the repo and create a branch from `main`.
2. Make the change with matching tests or documentation updates.
3. Run `uv run pre-commit run --all-files` and `uv run pytest` locally.
4. Open a pull request against `main`.
5. Wait for the EasyCLA check. If it blocks, follow the check link and sign the
   CLA.
6. Address maintainer review comments. Merge waits on tests, pre-commit, and
   CLA status.

## Bug reports and feature requests

Use GitHub issues. Include the command you ran, the expected behavior, the
actual behavior, and the relevant environment details: OS, Python version,
signal-bench version or commit SHA, hardware target, and telemetry sources.

For feature requests that affect methodology or public report numbers, describe
the measurement problem first. Implementation proposals are useful only after
the measurement problem is clear.

## License

Contributions are licensed under the [Apache License 2.0](LICENSE), matching
the project license, subject to the additional contributor grants in
[`CLA.md`](CLA.md).
