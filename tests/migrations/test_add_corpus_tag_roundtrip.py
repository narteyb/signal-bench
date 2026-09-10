# SPDX-License-Identifier: Apache-2.0
"""Roundtrip test for protocol corpus tags on runs."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import command
from sqlalchemy import Engine, inspect


def test_corpus_tag_roundtrip_preserves_legacy_marker(
    migration_roundtrip,
) -> None:
    """Migration 0004 adds corpus_tag, marks legacy rows, and cleanly removes it."""

    def assert_upgraded(engine: Engine) -> None:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("runs")}
        indexes = {index["name"] for index in inspector.get_indexes("runs")}

        assert "corpus_tag" in columns
        assert "idx_runs_corpus_tag" in indexes
        with engine.begin() as connection:
            corpus, extra = connection.execute(
                sa.text("SELECT corpus_tag, extra FROM runs WHERE run_id = 'legacy'"),
            ).one()
        assert corpus == "X"
        assert json.loads(extra)["pre_protocol"] is True

    def assert_downgraded(engine: Engine) -> None:
        columns = {column["name"] for column in inspect(engine).get_columns("runs")}
        assert "corpus_tag" not in columns

    cfg = migration_roundtrip.config()
    command.upgrade(cfg, "0003")
    with migration_roundtrip.engine() as engine, engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO targets(target_id, name, kind) " "VALUES('target', 'mock', 'mock')",
            ),
        )
        connection.execute(
            sa.text(
                "INSERT INTO tasks(task_id, name, version) " "VALUES('task', 'kws', 'v1')",
            ),
        )
        connection.execute(
            sa.text(
                "INSERT INTO runs("
                "run_id, target_id, task_id, started_at, status, warmup_count, "
                "measurement_count, signal_bench_version, extra"
                ") VALUES("
                "'legacy', 'target', 'task', '2026-05-18', 'completed', 0, 1, 'x', :extra"
                ")",
            ),
            {"extra": json.dumps({"kind": "benchmark"})},
        )

    command.upgrade(cfg, "0004")
    with migration_roundtrip.engine() as engine:
        assert_upgraded(engine)
    command.downgrade(cfg, "-1")
    with migration_roundtrip.engine() as engine:
        assert_downgraded(engine)
