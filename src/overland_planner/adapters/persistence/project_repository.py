"""`ProjectRepository` on SQLAlchemy Core, bound to the connection of one `SqlAlchemyUnitOfWork`."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from overland_planner.adapters.persistence.tables import projects
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from overland_planner.domain.catalog.project import Project, ProjectName

# Column values until the objective and project settings become editable (distance is the default objective).
_DEFAULT_OBJECTIVE = "distance"


class SqlAlchemyProjectRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, project: Project) -> None:
        self._connection.execute(
            projects.insert().values(
                id=project.id,
                name=project.name.value,
                objective=_DEFAULT_OBJECTIVE,
                settings={},
                revision=project.revision,
                created_at=project.created_at,
            )
        )

    def get(self, project_id: str) -> Project | None:
        row = self._connection.execute(select(projects).where(projects.c.id == project_id)).mappings().first()
        return None if row is None else _project(row)

    def list(self) -> list[Project]:
        rows = self._connection.execute(select(projects).order_by(projects.c.created_at, projects.c.id)).mappings()
        return [_project(row) for row in rows]


class SqlAlchemyCatalogUnitOfWork(SqlAlchemyUnitOfWork):
    """The unit of work with the catalog repositories bound to its transaction."""

    @property
    def projects(self) -> SqlAlchemyProjectRepository:
        return SqlAlchemyProjectRepository(self.connection)


def _project(row: Any) -> Project:
    return Project(id=row["id"], name=ProjectName(row["name"]), revision=row["revision"], created_at=row["created_at"])
