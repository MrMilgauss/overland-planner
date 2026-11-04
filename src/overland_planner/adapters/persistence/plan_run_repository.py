"""`PlanRunRepository` on SQLAlchemy Core, bound to the connection of one `SqlAlchemyUnitOfWork`."""

from __future__ import annotations

from sqlalchemy import Connection, select

from overland_planner.adapters.persistence.tables import plan_runs
from overland_planner.domain.planning.plan_run import PlanRun


class SqlAlchemyPlanRunRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list(self, project_id: str) -> list[PlanRun]:
        query = (
            select(plan_runs.c.id, plan_runs.c.number, plan_runs.c.status)
            .where(plan_runs.c.project_id == project_id)
            .order_by(plan_runs.c.number)
        )
        rows = self._connection.execute(query).mappings()
        return [PlanRun(id=row["id"], number=row["number"], status=row["status"]) for row in rows]
