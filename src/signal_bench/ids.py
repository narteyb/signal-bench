# SPDX-License-Identifier: Apache-2.0
"""UUIDv7 generation: sortable, time-ordered identifiers."""

from uuid_utils import uuid7


def new_id() -> str:
    """Return a UUIDv7 as a string. Sortable by creation time."""
    return str(uuid7())
