"""`CatalogUnitOfWork` adapter: the SQLAlchemy unit of work with the catalog repositories bound to its transaction."""

from __future__ import annotations

from overland_planner.adapters.persistence.item_repository import SqlAlchemyItemRepository
from overland_planner.adapters.persistence.project_repository import SqlAlchemyProjectRepository
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemyCatalogUnitOfWork(SqlAlchemyUnitOfWork):
    """The unit of work with the catalog repositories bound to its transaction."""

    @property
    def projects(self) -> SqlAlchemyProjectRepository:
        return SqlAlchemyProjectRepository(self.connection)

    @property
    def items(self) -> SqlAlchemyItemRepository:
        return SqlAlchemyItemRepository(self.connection)
