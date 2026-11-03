"""SQLite database of the planner (ADR-006, ADR-018, brief §9): `DATA_DIR/db/planner.sqlite`.

Every connection is opened with WAL journaling, foreign keys on and a 5 s busy timeout. The planner has one
process-wide writer lock: every writing unit of work holds it, so SQLite never sees two writers of ours at once.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event

BUSY_TIMEOUT_MS = 5000
_CONNECTION_PRAGMAS = ("PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON", f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")


def database_file(data_dir: Path) -> Path:
    return data_dir / "db" / "planner.sqlite"


def database_url(data_dir: Path) -> str:
    return f"sqlite:///{database_file(data_dir)}"


def _apply_pragmas(dbapi_connection: sqlite3.Connection, _record: Any) -> None:
    for pragma in _CONNECTION_PRAGMAS:
        dbapi_connection.execute(pragma).close()


class SqliteDatabase:
    def __init__(self, data_dir: Path) -> None:
        self.file = database_file(data_dir)
        self.writer_lock = threading.Lock()
        self.engine: Engine = create_engine(database_url(data_dir))
        event.listen(self.engine, "connect", _apply_pragmas)
