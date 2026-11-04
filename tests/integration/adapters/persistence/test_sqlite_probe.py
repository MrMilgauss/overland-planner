"""SQLite database start-up probe (brief §6 row "Repositories + UnitOfWork", ADR-006, ADR-018). Fatal on failure.

Integration level: single examples on a real SQLite file in a workspace data folder (never the OS temp folder,
ADR-011 D121) verify the wiring, then the gold fault catalogue: WAL silently off, a corrupted file, an unwritable
data folder. The refusal invariants live in tests/unit/bootstrap/test_startup_gate.py.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event

from overland_planner.adapters.clock.system_clock import SystemClock
from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.migrator import AlembicMigrator, DatabaseStartup
from overland_planner.application.ports.probe import ProbeResult
from tests.common.workspace import workspace_data_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATIONS = REPO_ROOT / "migrations"


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def _startup(data_dir: Path) -> tuple[SqliteDatabase, AlembicMigrator, DatabaseStartup]:
    database = SqliteDatabase(data_dir)
    migrator = AlembicMigrator(database, MIGRATIONS)
    return database, migrator, DatabaseStartup(database, migrator, SystemClock())


def test_a_fresh_data_folder_gets_a_database_at_head_with_wal_foreign_keys_and_busy_timeout(data_dir: Path) -> None:
    database, migrator, startup = _startup(data_dir)

    assert startup.probe() == ProbeResult(outcome="ok")

    with database.engine.connect() as connection:
        pragmas = {
            name: connection.exec_driver_sql(f"PRAGMA {name}").scalar()
            for name in ("journal_mode", "foreign_keys", "busy_timeout")
        }
    assert pragmas == {"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000}
    assert (data_dir / "db" / "planner.sqlite").is_file()
    assert migrator.current() == migrator.head() == "0005"


def test_wal_silently_off_is_fatal(data_dir: Path) -> None:
    database, _, startup = _startup(data_dir)

    @event.listens_for(database.engine, "connect")
    def _journal_falls_back(dbapi_connection: Any, _record: Any) -> None:  # e.g. a filesystem without shared memory
        dbapi_connection.execute("PRAGMA journal_mode=DELETE").close()

    assert startup.probe() == ProbeResult(outcome="fatal", reason="wal_not_active")


def test_a_corrupted_database_file_is_fatal(data_dir: Path) -> None:
    file = data_dir / "db" / "planner.sqlite"
    file.parent.mkdir()
    with sqlite3.connect(file) as seeded:
        seeded.execute("CREATE TABLE notes (body TEXT)")
        seeded.executemany("INSERT INTO notes VALUES (?)", [("x" * 200,) for _ in range(200)])
    seeded.close()
    with file.open("r+b") as raw:
        raw.seek(4096 * 2)
        raw.write(b"\xa5" * 4096 * 3)

    assert _startup(data_dir)[2].probe() == ProbeResult(outcome="fatal", reason="quick_check_failed")


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write to any folder")
def test_an_unwritable_data_folder_is_fatal(data_dir: Path) -> None:
    data_dir.chmod(0o555)

    assert _startup(data_dir)[2].probe() == ProbeResult(outcome="fatal", reason="data_dir_not_writable")
