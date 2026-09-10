# SPDX-License-Identifier: Apache-2.0
from uuid import UUID

from signal_bench.ids import new_id


def test_new_id_returns_string() -> None:
    assert isinstance(new_id(), str)


def test_new_id_is_uuidv7() -> None:
    assert UUID(new_id()).version == 7


def test_ids_are_sortable_by_time() -> None:
    ids = [new_id() for _ in range(100)]
    assert ids == sorted(ids)
