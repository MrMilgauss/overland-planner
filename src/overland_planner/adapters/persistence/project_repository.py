"""`ProjectRepository` on SQLAlchemy Core, bound to the connection of one `SqlAlchemyUnitOfWork`."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from overland_planner.adapters.persistence.tables import projects
from overland_planner.domain.catalog.anchors import Anchors
from overland_planner.domain.catalog.project import DEFAULT_OFFROAD_SPEED, OffroadSpeed, Project, ProjectName

# Column value until the objective becomes editable (distance is the default objective).
_DEFAULT_OBJECTIVE = "distance"
# `projects.settings` (brief §9, JSON since 0001): a project written before slice 02 has `{}` and drives 15 km/h.
_OFFROAD_SPEED_KEY = "offroad_speed_kmh"


class SqlAlchemyProjectRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, project: Project) -> None:
        self._connection.execute(
            projects.insert().values(
                id=project.id,
                name=project.name.value,
                objective=_DEFAULT_OBJECTIVE,
                settings=_settings(project),
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

    def update(self, project: Project) -> None:
        self._connection.execute(
            projects.update()
            .where(projects.c.id == project.id)
            .values(
                revision=project.revision,
                settings=_settings(project),
                start_item_id=project.anchors.start_item_id,
                end_item_id=project.anchors.end_item_id,
            )
        )


def _project(row: Any) -> Project:
    return Project(
        id=row["id"],
        name=ProjectName(row["name"]),
        revision=row["revision"],
        created_at=row["created_at"],
        anchors=Anchors(start_item_id=row["start_item_id"], end_item_id=row["end_item_id"]),
        offroad_speed=_offroad_speed(row["settings"]),
    )


def _settings(project: Project) -> dict[str, Any]:
    return {_OFFROAD_SPEED_KEY: project.offroad_speed.kmh}


def _offroad_speed(settings: dict[str, Any]) -> OffroadSpeed:
    stored = settings.get(_OFFROAD_SPEED_KEY)
    return DEFAULT_OFFROAD_SPEED if stored is None else OffroadSpeed(float(stored))
