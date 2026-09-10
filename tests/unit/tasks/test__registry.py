# SPDX-License-Identifier: Apache-2.0
from signal_bench.adapters.mcu.task import TaskSpec
from signal_bench.tasks import get_task, list_tasks


def test_list_tasks_returns_registered_names_sorted() -> None:
    assert list_tasks() == ["ad", "ic", "kws"]


def test_get_task_returns_fresh_task_spec() -> None:
    first = get_task("kws")
    second = get_task("kws")

    assert isinstance(first, TaskSpec)
    assert first is not second
    assert first.task_id == "kws"


def test_get_task_unknown_raises_with_available_tasks() -> None:
    try:
        get_task("missing")
    except KeyError as exc:
        message = str(exc)
    else:
        msg = "expected KeyError"
        raise AssertionError(msg)

    assert "Unknown task" in message
    assert "ad" in message
    assert "ic" in message
    assert "kws" in message
