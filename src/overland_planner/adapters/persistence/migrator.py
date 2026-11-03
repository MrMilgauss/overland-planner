"""Alembic migrations at start-up and the database start-up probe (brief §6 and §7, ADR-006, ADR-018, D129).

`AlembicMigrator` runs the planner's own `migrations/` (setting MIGRATIONS_DIR) on its database and reads the stored
revision read-only, before anything opens the database for writing.

`DatabaseStartup` is the component the composition root registers as `database`. Its probe first reads the stored
revision read-only and lets the migration policy (application/platform) decide: a revision this planner does not know
is fatal `db_newer_than_app` with nothing written, copied or created (no -wal/-shm side files either); an older known
revision is copied to `db/backups/planner-{rev}-{ts}.sqlite` with the SQLite backup API (newest three kept) before the
upgrade; a fresh database is upgraded; one at head is left as it is. Then it checks integrity and proves the database
works: WAL active, foreign keys on, busy timeout set, a write-read round trip through a unit of work, and the Alembic
head. Every failure is fatal; the reason names the check.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from overland_planner.adapters.persistence.database import BUSY_TIMEOUT_MS, SqliteDatabase
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from overland_planner.application.platform.facade import MigrationAction, PreMigrationCopies, RevisionChain
from overland_planner.application.ports.clock import Clock
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

    def chain(self) -> RevisionChain:
        """The planner's own revisions, oldest first."""
        newest_first = [script.revision for script in ScriptDirectory.from_config(self._config).walk_revisions()]
        return RevisionChain.of(newest_first[::-1])

    def stored_revision(self) -> str | None:
        """The revision stored in the database, read without writing anything.

        Without a -wal file the main file holds every committed page, so it is opened `immutable` (SQLite then creates
        no -wal/-shm side file); a -wal left by an unclean stop must be read, so then plain read-only mode is used and
        the side files that already exist are reused.
        """
        file = self._database.file
        if not file.exists():
            return None
        mode = "mode=ro" if file.with_name(f"{file.name}-wal").exists() else "mode=ro&immutable=1"
        reader = sqlite3.connect(f"{file.resolve().as_uri()}?{mode}", uri=True)
        try:
            if reader.execute("SELECT 1 FROM sqlite_master WHERE name = 'alembic_version'").fetchone() is None:
                return None
            row = reader.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            reader.close()
        return None if row is None else str(row[0])

    def copy_to(self, target: Path) -> None:
        """A consistent copy of the database through the SQLite backup API."""
        copy = sqlite3.connect(target)
        try:
            with self._database.writer_lock, self._database.engine.connect() as connection:
                cast(sqlite3.Connection, connection.connection.driver_connection).backup(copy)
        finally:
            copy.close()

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


_Checks = tuple[tuple[str, Callable[[], bool]], ...]


def _first_failure(checks: _Checks) -> ProbeResult:
    """Run the checks in order; the first one that fails or raises is fatal with its reason."""
    for reason, check in checks:
        try:
            passed = check()
        except Exception:  # any error of the check is its failure; the reason names the check
            passed = False
        if not passed:
            return ProbeResult(outcome="fatal", reason=reason)
    return ProbeResult(outcome="ok")


class DatabaseStartup:
    def __init__(self, database: SqliteDatabase, migrator: AlembicMigrator, clock: Clock) -> None:
        self._database = database
        self._migrator = migrator
        self._clock = clock

    def probe(self) -> ProbeResult:
        if not self._data_dir_writable():
            return ProbeResult(outcome="fatal", reason="data_dir_not_writable")
        try:
            stored = self._migrator.stored_revision()
            action = self._migrator.chain().action_for(stored)
        except Exception:  # an unreadable revision is fatal before anything is written
            return ProbeResult(outcome="fatal", reason="revision_unreadable")
        if action is MigrationAction.REFUSE_NEWER:
            return ProbeResult(outcome="fatal", reason="db_newer_than_app")
        return _first_failure(self._checks(action, stored))

    def _data_dir_writable(self) -> bool:
        folder = self._database.file.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return os.access(folder, os.W_OK)

    def _checks(self, action: MigrationAction, stored: str | None) -> _Checks:
        """Migrate as the policy says, then prove the database works; each check named by its failure reason."""
        return (
            ("quick_check_failed", self._quick_check),
            (
                "pre_migration_copy_failed",
                lambda: action is not MigrationAction.COPY_THEN_UPGRADE or self._copy(stored),
            ),
            ("migration_failed", lambda: action is MigrationAction.NOTHING or self._upgrade()),
            ("wal_not_active", lambda: self._pragma("journal_mode") == "wal"),
            ("foreign_keys_off", lambda: self._pragma("foreign_keys") == 1),
            ("busy_timeout_not_set", lambda: self._pragma("busy_timeout") == BUSY_TIMEOUT_MS),
            ("round_trip_failed", self._round_trip),
            ("not_at_head", lambda: self._migrator.current() == self._migrator.head()),
        )

    def _pragma(self, name: str) -> object:
        with self._database.engine.connect() as connection:
            return connection.exec_driver_sql(f"PRAGMA {name}").scalar()

    def _quick_check(self) -> bool:
        return self._pragma("quick_check") == "ok"

    def _copy(self, revision: str | None) -> bool:
        backups = self._database.file.parent / "backups"
        backups.mkdir(exist_ok=True)
        self._migrator.copy_to(backups / PreMigrationCopies.name_for(str(revision), self._clock.now()))
        for name in PreMigrationCopies.to_prune(entry.name for entry in backups.iterdir()):
            (backups / name).unlink()
        return True

    def _upgrade(self) -> bool:
        self._migrator.upgrade_to_head()
        return True

    def _round_trip(self) -> bool:
        token = secrets.randbelow(2**31 - 1) + 1
        with SqlAlchemyUnitOfWork(self._database) as unit_of_work:
            unit_of_work.connection.exec_driver_sql(f"PRAGMA user_version = {token}")
            unit_of_work.commit()
        return self._pragma("user_version") == token
