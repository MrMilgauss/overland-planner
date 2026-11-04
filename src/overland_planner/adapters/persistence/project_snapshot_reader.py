"""`ProjectSnapshotReader` on SQLAlchemy Core, bound to the connection of one `SqlAlchemyUnitOfWork`."""

from __future__ import annotations

from sqlalchemy import Connection, select

from overland_planner.adapters.persistence.item_repository import SqlAlchemyItemRepository
from overland_planner.adapters.persistence.tables import projects
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot


class SqlAlchemyProjectSnapshotReader:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def read(self, project_id: str) -> ProjectSnapshot | None:
        """Items in the order they were added (`items.position`): node order follows it, so solves are deterministic."""
        query = select(projects.c.start_item_id, projects.c.end_item_id).where(projects.c.id == project_id)
        row = self._connection.execute(query).mappings().first()
        if row is None:
            return None
        items = tuple(SqlAlchemyItemRepository(self._connection).list(project_id))
        return ProjectSnapshot(row["start_item_id"], row["end_item_id"], items)

    def stamp(self, project_id: str) -> ProjectStamp:
        query = select(projects.c.revision, projects.c.objective).where(projects.c.id == project_id)
        row = self._connection.execute(query).mappings().one()
        return ProjectStamp(revision=row["revision"], objective=row["objective"])
