# SPDX-License-Identifier: Apache-2.0
"""Roundtrip test for telemetry partial run columns."""

from __future__ import annotations

from sqlalchemy import Engine, inspect

EXPECTED_TABLES = {"targets", "tasks", "runs", "results", "telemetry_samples", "alembic_version"}


def test_telemetry_partial_columns_roundtrip(
    migration_roundtrip,
) -> None:
    """Migration 0002 adds telemetry_partial columns and cleanly removes them."""

    def assert_upgraded(engine: Engine) -> None:
        columns = {column["name"] for column in inspect(engine).get_columns("runs")}
        assert "telemetry_partial" in columns
        assert "telemetry_partial_sources" in columns

    def assert_downgraded(engine: Engine) -> None:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("runs")}
        assert "telemetry_partial" not in columns
        assert "telemetry_partial_sources" not in columns
        assert set(inspector.get_table_names()) == EXPECTED_TABLES

    migration_roundtrip.assert_revision_roundtrip(
        "0002",
        before="0001",
        assert_upgraded=assert_upgraded,
        assert_downgraded=assert_downgraded,
    )
