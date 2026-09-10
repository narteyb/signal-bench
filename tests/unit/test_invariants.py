# SPDX-License-Identifier: Apache-2.0
import ast
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[2] / "src" / "signal_bench"


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _assert_core_does_not_import(module_name: str) -> None:
    offenders = [path for path in CORE_ROOT.rglob("*.py") if module_name in _imported_modules(path)]
    assert offenders == []


def test_signal_bench_does_not_import_click() -> None:
    _assert_core_does_not_import("click")


def test_signal_bench_does_not_import_rich() -> None:
    _assert_core_does_not_import("rich")


def test_signal_bench_does_not_import_signal_bench_cli() -> None:
    _assert_core_does_not_import("signal_bench_cli")
