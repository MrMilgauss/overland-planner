"""`PlanJobLog` on SQLAlchemy Core (ADR-015 DV-2, ADR-018): one append-only `plan_job_log` row per ended job.

Each row is written in its own transaction under the single writer lock, with this planner's `app_version` (the
`PLANNER_GIT_SHA` the event lines carry). The probe writes and reads one row in a transaction it rolls back, under the
same lock, so a table that cannot be written refuses the start like the database (fatal), and no row is left.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Connection, func, select
from sqlalchemy.exc import SQLAlchemyError

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.tables import plan_job_log
from overland_planner.application.ports.plan_job_log import PlanJobLogEntry
from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure

_PROBE_JOB_ID = "probe"
_PROBE_AT = datetime(2000, 1, 1, tzinfo=UTC)
_PROBE_ENTRY = PlanJobLogEntry(
    _PROBE_AT,
    _PROBE_AT,
    {
        "job_id": _PROBE_JOB_ID,
        "project_id": _PROBE_JOB_ID,
        "terminal_state": "failed",
        "memo_hit": False,
        "ignore_memo": False,
        "elapsed_ms": 0,
    },
)


class SqlAlchemyPlanJobLog:
    def __init__(self, database: SqliteDatabase, *, app_version: str) -> None:
        self._database = database
        self._app_version = app_version

    def append(self, entry: PlanJobLogEntry) -> None:
        with self._database.writer_lock, self._database.engine.begin() as connection:
            self._insert(connection, entry)

    def probe(self) -> ProbeResult:
        check = ProbeCheck("plan_job_log_unwritable", self._round_trip)
        return first_failure((check,), failing_errors=(SQLAlchemyError,))

    def _round_trip(self) -> bool:
        with self._database.writer_lock, self._database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                self._insert(connection, _PROBE_ENTRY)
                query = select(func.count()).where(plan_job_log.c.job_id == _PROBE_JOB_ID)
                return bool(connection.execute(query).scalar_one() == 1)
            finally:
                transaction.rollback()

    def _insert(self, connection: Connection, entry: PlanJobLogEntry) -> None:
        connection.execute(plan_job_log.insert().values(**entry.columns(), app_version=self._app_version))
