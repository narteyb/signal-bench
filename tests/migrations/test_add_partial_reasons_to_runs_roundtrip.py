# SPDX-License-Identifier: Apache-2.0
"""Roundtrip test for telemetry partial reason column."""

from __future__ import annotations

from sqlalchemy import Engine, inspect


def test_partial_reasons_column_roundtrip(
    migration_roundtrip,
) -> None:
    """Migration 0003 adds partial_reasons and cleanly removes it."""

    def assert_upgraded(engine: Engine) -> None:
        columns = {column["name"] for column in inspect(engine).get_columns("runs")}
        assert "partial_reasons" in columns

    def assert_downgraded(engine: Engine) -> None:
        columns = {column["name"] for column in inspect(engine).get_columns("runs")}
        assert "partial_reasons" not in columns
        assert "telemetry_partial" in columns
        assert "telemetry_partial_sources" in columns

    migration_roundtrip.assert_revision_roundtrip(
        "0003",
        before="0002",
        assert_upgraded=assert_upgraded,
        assert_downgraded=assert_downgraded,
    )
