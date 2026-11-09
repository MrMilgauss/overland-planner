"""`PlanningUnitOfWork` adapter: the SQLAlchemy unit of work with planning's repositories bound to its transaction."""

from __future__ import annotations

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.plan_run_repository import SqlAlchemyPlanRunRepository
from overland_planner.adapters.persistence.project_snapshot_reader import SqlAlchemyProjectSnapshotReader
from overland_planner.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from overland_planner.application.ports.event_log import EventLog


class SqlAlchemyPlanningUnitOfWork(SqlAlchemyUnitOfWork):
    """The unit of work with planning's repositories bound to its transaction."""

    def __init__(self, database: SqliteDatabase, event_log: EventLog) -> None:
        super().__init__(database)
        self._event_log = event_log

    @property
    def plan_runs(self) -> SqlAlchemyPlanRunRepository:
        return SqlAlchemyPlanRunRepository(self.connection)

    @property
    def project_snapshots(self) -> SqlAlchemyProjectSnapshotReader:
        return SqlAlchemyProjectSnapshotReader(self.connection, self._event_log)
