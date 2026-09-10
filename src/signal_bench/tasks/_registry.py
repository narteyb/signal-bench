# SPDX-License-Identifier: Apache-2.0
"""Task registry for benchmark dispatch."""

from __future__ import annotations

from collections.abc import Callable

from signal_bench.adapters.mcu.task import TaskSpec

TaskFactory = Callable[[], TaskSpec]

_REGISTRY: dict[str, TaskFactory] = {}


def register_task(factory: TaskFactory) -> TaskFactory:
    """Register a task factory under its function name."""
    _REGISTRY[factory.__name__] = factory
    return factory


def get_task(name: str) -> TaskSpec:
    """Return a fresh task specification by name."""
    try:
        return _REGISTRY[name]()
    except KeyError as exc:
        available = ", ".join(list_tasks())
        msg = f"Unknown task: {name}. Available tasks: {available}"
        raise KeyError(msg) from exc


def list_tasks() -> list[str]:
    """Return all registered task names in stable order."""
    return sorted(_REGISTRY)
