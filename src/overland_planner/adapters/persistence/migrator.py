"""Alembic migrations at start-up and the database start-up probe (brief §6 and §7, ADR-006, ADR-018, D129).

`AlembicMigrator` runs the planner's own `migrations/` (setting MIGRATIONS_DIR) on its database. This slice handles a
fresh database or one already at head; newer and older revisions (refusal, pre-migration copy) arrive with 03-01.

`DatabaseStartup` is the component the composition root registers as `database`. Its probe prepares the database
(folder, integrity, upgrade to head) and then proves it works: WAL active, foreign keys on, busy timeout set, a
write-read round trip through a unit of work, and the Alembic head. Every failure is fatal; the reason names the check.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from overland_planner.adapters.persistence.database import BUSY_TIMEOUT_MS, SqliteDatabase
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from overland_planner.application.ports.probe import ProbeResult


class AlembicMigrator:
    def __init__(self, database: SqliteDatabase, migrations_dir: Path) -> None:
        self._database = database
        self._config = Config()
        self._config.set_main_option("script_location", str(migrations_dir))
        self._config.set_main_option("path_separator", "os")
        self._config.set_main_option("version_locations", str(migrations_dir / "versions"))
        self._config.set_main_option("sqlalchemy.url", database.engine.url.render_as_string(hide_password=False))

    def head(self) -> str | None:
        return ScriptDirectory.from_config(self._config).get_current_head()

    def current(self) -> str | None:
        with self._database.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def upgrade_to_head(self) -> None:
        with self._database.writer_lock, self._database.engine.begin() as connection:
            self._config.attributes["connection"] = connection
            try:
                command.upgrade(self._config, "head")
            finally:
                del self._config.attributes["connection"]


class DatabaseStartup:
    def __init__(self, database: SqliteDatabase, migrator: AlembicMigrator) -> None:
        self._database = database
        self._migrator = migrator

    def probe(self) -> ProbeResult:
        folder = self._database.file.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ProbeResult(outcome="fatal", reason="data_dir_not_writable")
        if not os.access(folder, os.W_OK):
            return ProbeResult(outcome="fatal", reason="data_dir_not_writable")
        checks: tuple[tuple[str, Callable[[], bool]], ...] = (
            ("quick_check_failed", self._quick_check),
            ("migration_failed", self._upgrade),
            ("wal_not_active", lambda: self._pragma("journal_mode") == "wal"),
            ("foreign_keys_off", lambda: self._pragma("foreign_keys") == 1),
            ("busy_timeout_not_set", lambda: self._pragma("busy_timeout") == BUSY_TIMEOUT_MS),
            ("round_trip_failed", self._round_trip),
            ("not_at_head", lambda: self._migrator.current() == self._migrator.head()),
        )
        for reason, check in checks:
            try:
                passed = check()
            except Exception:  # any error of the check is its failure; the reason names the check
                passed = False
            if not passed:
                return ProbeResult(outcome="fatal", reason=reason)
        return ProbeResult(outcome="ok")

    def _pragma(self, name: str) -> object:
        with self._database.engine.connect() as connection:
            return connection.exec_driver_sql(f"PRAGMA {name}").scalar()

    def _quick_check(self) -> bool:
        return self._pragma("quick_check") == "ok"

    def _upgrade(self) -> bool:
        self._migrator.upgrade_to_head()
        return True

    def _round_trip(self) -> bool:
        token = secrets.randbelow(2**31 - 1) + 1
        with SqlAlchemyUnitOfWork(self._database) as unit_of_work:
            unit_of_work.connection.exec_driver_sql(f"PRAGMA user_version = {token}")
            unit_of_work.commit()
        return self._pragma("user_version") == token
