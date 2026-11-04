"""`ProjectSnapshotReader` on SQLAlchemy Core, bound to the connection of one `SqlAlchemyUnitOfWork`."""

from __future__ import annotations

from sqlalchemy import Connection, select

from overland_planner.adapters.persistence.tables import projects
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot


class SqlAlchemyProjectSnapshotReader:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def read(self, project_id: str) -> ProjectSnapshot | None:
        query = select(projects.c.start_item_id, projects.c.end_item_id).where(projects.c.id == project_id)
        row = self._connection.execute(query).mappings().first()
        return None if row is None else ProjectSnapshot(row["start_item_id"], row["end_item_id"])
