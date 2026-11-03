"""`UnitOfWork` adapter on SQLAlchemy Core: one connection and one transaction under the writer lock."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy import Connection

from overland_planner.adapters.persistence.database import SqliteDatabase


class SqlAlchemyUnitOfWork:
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database
        self._connection: Connection | None = None

    @property
    def connection(self) -> Connection:
        """The transaction's connection, for the repositories bound to this unit of work."""
        if self._connection is None:
            raise RuntimeError("the unit of work is not open")
        return self._connection

    def __enter__(self) -> Self:
        self._database.writer_lock.acquire()
        try:
            self._connection = self._database.engine.connect()
            self._connection.begin()
        except BaseException:
            self._database.writer_lock.release()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.connection.rollback()  # no-op after commit()
            self.connection.close()
        finally:
            self._connection = None
            self._database.writer_lock.release()

    def commit(self) -> None:
        self.connection.commit()
