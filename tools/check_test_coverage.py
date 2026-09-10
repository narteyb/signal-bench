# SPDX-License-Identifier: Apache-2.0
"""Enforce signal-bench INV-09 test counterpart requirements."""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Requirement:
    """One expected source-to-test counterpart."""

    source: str
    category: str
    required: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Gap:
    """One missing test requirement."""

    source: str
    category: str
    missing: tuple[str, ...]


def main() -> int:
    """Check every tracked source file has its required test counterparts."""
    known = load_known_non_test_files()
    known_prefixes = load_known_non_test_prefixes()
    tracked = git_ls_files()
    test_files = repo_files_under("tests")

    requirements: list[Requirement] = []
    uncategorized: list[str] = []
    for source in tracked_sources(tracked):
        if source in known or any(source.startswith(prefix) for prefix in known_prefixes):
            continue
        requirement = classify(source)
        if requirement is None:
            uncategorized.append(source)
        else:
            requirements.append(requirement)

    gaps = [
        Gap(
            source=req.source,
            category=req.category,
            missing=tuple(path for path in req.required if path not in test_files),
        )
        for req in requirements
    ]
    gaps = [gap for gap in gaps if gap.missing]

    if uncategorized or gaps:
        print("INV-09 test coverage check failed.")
        if uncategorized:
            print("\nUncategorized files:")
            for source in uncategorized:
                print(f"  - {source}")
            print(
                "Add tests or acknowledge the file in tests.conftest.KNOWN_NON_TEST_FILES "
                "or KNOWN_NON_TEST_PREFIXES."
            )
        if gaps:
            print("\nMissing required tests:")
            for gap in gaps:
                missing = ", ".join(gap.missing)
                print(f"  - {gap.source} [{gap.category}] -> {missing}")
        return 1

    print(f"INV-09 test coverage check passed ({len(requirements)} source files enforced).")
    return 0


def git_ls_files() -> list[str]:
    """Return tracked repo files."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def tracked_sources(files: list[str]) -> list[str]:
    """Return tracked files in the INV-09 enforcement scope."""
    prefixes = (
        "src/signal_bench/",
        "src/signal_bench_cli/",
        "experiments/",
    )
    sources = [path for path in files if path.startswith(prefixes)]
    sources.extend(
        path
        for path in files
        if path.startswith("src/signal_bench/migrations/versions/") and path.endswith(".py")
    )
    return sorted(set(sources))


def repo_files_under(directory: str) -> set[str]:
    """Return current working tree files below a directory."""
    root = ROOT / directory
    if not root.exists():
        return set()
    return {
        path.relative_to(ROOT).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def classify(source: str) -> Requirement | None:
    """Classify one source path into its deterministic test requirements."""
    special = special_requirement(source)
    if special is not None:
        return special

    if source.startswith("src/signal_bench/migrations/versions/") and source.endswith(".py"):
        name = source.removeprefix("src/signal_bench/migrations/versions/")
        test_name = migration_test_name(name)
        return Requirement(source, "migration", (f"tests/migrations/{test_name}",))

    if source.startswith("src/signal_bench_cli/commands/") and source.endswith(".py"):
        command = Path(source).stem
        return Requirement(
            source,
            "cli command",
            (
                f"tests/integration/test_{command}_command.py",
                f"tests/e2e/test_{command}_subprocess.py",
            ),
        )

    if source.startswith("src/signal_bench/") and source.endswith(".py"):
        rel = source.removeprefix("src/signal_bench/").removesuffix(".py")
        parts = rel.split("/")
        if len(parts) == 1:
            return Requirement(source, "core module", (f"tests/unit/test_{parts[0]}.py",))
        package = "/".join(parts[:-1])
        module = parts[-1]
        required = [f"tests/unit/{package}/test_{module}.py"]
        if is_mock_module(source):
            required.append(f"tests/spec_fidelity/{package}/test_{module}_fidelity.py")
        category = "mock impl" if is_mock_module(source) else "core module"
        return Requirement(source, category, tuple(required))

    if source.startswith("experiments/") and source.endswith(".py"):
        experiment = experiment_name_for(source)
        if experiment is not None:
            return Requirement(
                source,
                "experiment",
                (
                    f"tests/experiments/test_{experiment}_smoke.py",
                    f"tests/experiments/test_{experiment}_reproducibility.py",
                ),
            )
        if source.startswith("experiments/lib/"):
            return Requirement(
                source,
                "experiment support",
                (
                    "tests/experiments/test_e01_llm_baseline_smoke.py",
                    "tests/experiments/test_e01_llm_baseline_reproducibility.py",
                ),
            )

    return None


def special_requirement(source: str) -> Requirement | None:
    """Return explicit requirements for files that use non-default test layouts."""
    requirements = {
        "src/signal_bench_cli/__main__.py": Requirement(
            source,
            "cli entrypoint",
            ("tests/e2e/test_main_subprocess.py",),
        ),
        "src/signal_bench/adapters/mcu/command.py": Requirement(
            source,
            "mcu command adapter",
            ("tests/adapters/mcu/test_command_adapter.py",),
        ),
        "src/signal_bench/adapters/mcu/base.py": Requirement(
            source,
            "mcu adapter base",
            (
                "tests/adapters/mcu/test_base_config.py",
                "tests/adapters/mcu/test_base_lifecycle.py",
                "tests/adapters/mcu/test_base_measure_errors.py",
                "tests/adapters/mcu/test_base_measure_happy.py",
                "tests/adapters/mcu/test_base_thermal_osinfo.py",
                "tests/adapters/mcu/test_base_timeouts.py",
            ),
        ),
        "src/signal_bench/analysis/__init__.py": Requirement(
            source,
            "analysis package marker",
            ("tests/unit/analysis/test_timing.py",),
        ),
        "src/signal_bench/analysis/_reports.py": Requirement(
            source,
            "analysis report helpers",
            ("tests/unit/analysis/test_timing.py",),
        ),
        "src/signal_bench/analysis/exceptions.py": Requirement(
            source,
            "analysis exceptions",
            ("tests/unit/analysis/test_timing.py",),
        ),
        "src/signal_bench/archive.py": Requirement(
            source,
            "archive persistence",
            ("tests/test_archive.py",),
        ),
        "src/signal_bench/eval/__init__.py": Requirement(
            source,
            "evaluation package marker",
            ("tests/eval/test_full_eval.py",),
        ),
        "src/signal_bench/eval/full_eval.py": Requirement(
            source,
            "evaluation metrics",
            ("tests/eval/test_full_eval.py",),
        ),
        "src/signal_bench/orchestrator.py": Requirement(
            source,
            "orchestrator",
            ("tests/test_orchestrator.py",),
        ),
        "src/signal_bench/phase1/__init__.py": Requirement(
            source,
            "phase1 package marker",
            ("tests/unit/phase1/test_imports.py",),
        ),
        "src/signal_bench/phase1/environment.py": Requirement(
            source,
            "phase1 environment capture",
            ("tests/unit/phase1/test_comparison.py",),
        ),
        "src/signal_bench/phase1/report.py": Requirement(
            source,
            "phase1 report",
            ("tests/unit/phase1/test_comparison.py",),
        ),
        "src/signal_bench/phase1/runtime.py": Requirement(
            source,
            "phase1 runtime contracts",
            (
                "tests/unit/phase1/test_adapters.py",
                "tests/unit/phase1/test_accuracy.py",
                "tests/unit/phase1/test_harness.py",
            ),
        ),
        "src/signal_bench/phase1/telemetry.py": Requirement(
            source,
            "phase1 telemetry",
            ("tests/unit/phase1/test_harness.py",),
        ),
        "src/signal_bench/phase1/workload.py": Requirement(
            source,
            "phase1 workload",
            (
                "tests/unit/phase1/test_accuracy.py",
                "tests/unit/phase1/test_comparison.py",
            ),
        ),
        "src/signal_bench/protocols/__init__.py": Requirement(
            source,
            "protocol package marker",
            ("tests/test_corpus_tag.py",),
        ),
        "src/signal_bench/synth/_partial.py": Requirement(
            source,
            "partial-aware synthesis",
            (
                "tests/unit/synth/test_partial_aware_aggregation.py",
                "tests/unit/synth/test_partial_inference_warnings.py",
            ),
        ),
        "src/signal_bench/synth/matrix_data.py": Requirement(
            source,
            "matrix data contracts",
            (
                "tests/unit/synth/test_chart_data.py",
                "tests/unit/synth/test_exporter.py",
                "tests/unit/synth/test_report.py",
            ),
        ),
        "src/signal_bench_cli/commands/eval.py": Requirement(
            source,
            "eval command",
            ("tests/test_model_lineage.py",),
        ),
        "src/signal_bench_cli/commands/inspect.py": Requirement(
            source,
            "inspect command",
            (
                "tests/test_inspect_cli.py",
                "tests/test_corpus_tag.py",
                "tests/test_failures.py",
            ),
        ),
        "src/signal_bench_cli/commands/phase1.py": Requirement(
            source,
            "phase1 command",
            ("tests/unit/phase1/test_harness.py",),
        ),
        "src/signal_bench_cli/commands/spot_check.py": Requirement(
            source,
            "spot-check command",
            ("tests/test_corpus_tag.py",),
        ),
        "src/signal_bench_cli/commands/synth.py": Requirement(
            source,
            "synth command",
            ("tests/integration/test_synth_report.py",),
        ),
    }
    return requirements.get(source)


def is_mock_module(source: str) -> bool:
    """Return True when the source file is a mock implementation."""
    if Path(source).stem.endswith("_mock") or Path(source).stem == "mock":
        return True
    try:
        tree = ast.parse((ROOT / source).read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ClassDef) and node.name.endswith("Mock") for node in ast.walk(tree)
    )


def migration_test_name(filename: str) -> str:
    """Map an Alembic filename to a roundtrip test filename."""
    stem = filename.removesuffix(".py")
    parts = stem.split("_", 1)
    name = parts[1] if len(parts) == 2 else stem
    return f"test_{name}_roundtrip.py"


def experiment_name_for(source: str) -> str | None:
    """Return experiment directory name for an experiment source path."""
    parts = Path(source).parts
    if len(parts) >= 3 and parts[0] == "experiments" and parts[1].startswith("e"):
        return parts[1]
    return None


def load_known_non_test_files() -> set[str]:
    """Load explicitly acknowledged non-test files from tests.conftest."""
    sys.path.insert(0, str(ROOT))
    try:
        from tests.conftest import KNOWN_NON_TEST_FILES
    finally:
        sys.path.pop(0)
    return set(KNOWN_NON_TEST_FILES)


def load_known_non_test_prefixes() -> set[str]:
    """Load acknowledged non-test file prefixes from tests.conftest."""
    sys.path.insert(0, str(ROOT))
    try:
        from tests.conftest import KNOWN_NON_TEST_PREFIXES
    finally:
        sys.path.pop(0)
    return set(KNOWN_NON_TEST_PREFIXES)


if __name__ == "__main__":
    raise SystemExit(main())
