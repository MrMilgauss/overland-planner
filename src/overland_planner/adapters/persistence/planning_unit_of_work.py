"""`PlanningUnitOfWork` adapter: the SQLAlchemy unit of work with planning's repositories bound to its transaction."""

from __future__ import annotations

from overland_planner.adapters.persistence.plan_run_repository import SqlAlchemyPlanRunRepository
from overland_planner.adapters.persistence.project_snapshot_reader import SqlAlchemyProjectSnapshotReader
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemyPlanningUnitOfWork(SqlAlchemyUnitOfWork):
    """The unit of work with planning's repositories bound to its transaction."""

    @property
    def plan_runs(self) -> SqlAlchemyPlanRunRepository:
        return SqlAlchemyPlanRunRepository(self.connection)

    @property
    def project_snapshots(self) -> SqlAlchemyProjectSnapshotReader:
        return SqlAlchemyProjectSnapshotReader(self.connection)
