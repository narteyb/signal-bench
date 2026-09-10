# SPDX-License-Identifier: Apache-2.0
"""Reusable Alembic migration roundtrip helpers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class MigrationRoundtrip:
    """Assert one migration can apply and reverse cleanly."""

    db_path: Path

    def config(self) -> Config:
        """Return an Alembic Config pointed at the temporary SQLite database."""
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")
        return cfg

    @contextmanager
    def engine(self) -> Iterator[Engine]:
        """Yield an engine for the temporary database."""
        engine = create_engine(f"sqlite:///{self.db_path}")
        try:
            yield engine
        finally:
            engine.dispose()

    def assert_revision_roundtrip(
        self,
        revision: str,
        *,
        before: str = "base",
        assert_upgraded: Callable[[Engine], None],
        assert_downgraded: Callable[[Engine], None],
    ) -> None:
        """Upgrade to a revision, assert state, downgrade one step, assert prior state."""
        cfg = self.config()
        command.upgrade(cfg, before)
        command.upgrade(cfg, revision)
        with self.engine() as engine:
            assert_upgraded(engine)
        command.downgrade(cfg, "-1")
        with self.engine() as engine:
            assert_downgraded(engine)


@pytest.fixture
def migration_roundtrip(tmp_path) -> MigrationRoundtrip:
    """Return a reusable migration roundtrip assertion helper."""
    return MigrationRoundtrip(tmp_path / "migration.db")
