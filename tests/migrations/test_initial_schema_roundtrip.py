# SPDX-License-Identifier: Apache-2.0
"""Roundtrip test for the initial schema migration."""

from __future__ import annotations

from sqlalchemy import Engine, inspect

EXPECTED_TABLES = {"targets", "tasks", "runs", "results", "telemetry_samples", "alembic_version"}


def test_initial_schema_roundtrip(migration_roundtrip) -> None:
    """Migration 0001 creates the five schema tables and reverses to base."""

    def assert_upgraded(engine: Engine) -> None:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES

    def assert_downgraded(engine: Engine) -> None:
        assert inspect(engine).get_table_names() == ["alembic_version"]

    migration_roundtrip.assert_revision_roundtrip(
        "0001",
        assert_upgraded=assert_upgraded,
        assert_downgraded=assert_downgraded,
    )
