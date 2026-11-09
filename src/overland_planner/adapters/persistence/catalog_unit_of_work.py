"""`CatalogUnitOfWork` adapter: the SQLAlchemy unit of work with the catalog repositories bound to its transaction."""

from __future__ import annotations

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.item_repository import SqlAlchemyItemRepository
from overland_planner.adapters.persistence.project_repository import SqlAlchemyProjectRepository
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from overland_planner.application.ports.event_log import EventLog


class SqlAlchemyCatalogUnitOfWork(SqlAlchemyUnitOfWork):
    """The unit of work with the catalog repositories bound to its transaction."""

    def __init__(self, database: SqliteDatabase, event_log: EventLog) -> None:
        super().__init__(database)
        self._event_log = event_log

    @property
    def projects(self) -> SqlAlchemyProjectRepository:
        return SqlAlchemyProjectRepository(self.connection, self._event_log)

    @property
    def items(self) -> SqlAlchemyItemRepository:
        return SqlAlchemyItemRepository(self.connection)
