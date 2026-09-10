# SPDX-License-Identifier: Apache-2.0
"""Roundtrip test for first-class protocol failure records."""

from __future__ import annotations

from sqlalchemy import Engine, inspect


def test_failures_table_roundtrip(
    migration_roundtrip,
) -> None:
    """Migration 0005 creates failures and cleanly removes it."""

    def assert_upgraded(engine: Engine) -> None:
        inspector = inspect(engine)
        assert "failures" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("failures")}
        assert {
            "failure_id",
            "target_id",
            "task_id",
            "corpus_tag",
            "failure_mode",
            "diagnostic_signature",
            "toolchain_versions",
        }.issubset(columns)
        indexes = {index["name"] for index in inspector.get_indexes("failures")}
        assert "idx_failures_target_task" in indexes

    def assert_downgraded(engine: Engine) -> None:
        assert "failures" not in inspect(engine).get_table_names()

    migration_roundtrip.assert_revision_roundtrip(
        "0005",
        before="0004",
        assert_upgraded=assert_upgraded,
        assert_downgraded=assert_downgraded,
    )
