# SPDX-License-Identifier: Apache-2.0
"""Post 1 TinyML task registry."""

from signal_bench.adapters.mcu.task import TaskSpec
from signal_bench.tasks import ad as _ad
from signal_bench.tasks import ic as _ic
from signal_bench.tasks import kws as _kws
from signal_bench.tasks._registry import get_task, list_tasks, register_task

__all__ = [
    "TaskSpec",
    "get_task",
    "list_tasks",
    "register_task",
]

_ = (_ad, _ic, _kws)
