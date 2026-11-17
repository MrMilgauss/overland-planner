"""`PlanRefusalLog` on SQLAlchemy Core (ADR-013 Amendment 4, D248): one append-only `plan_refusals` row per refusal.

Each row is written in its own transaction under the single writer lock, stamped by the `Clock` port. The probe
writes and reads one row in a transaction it rolls back, under the same lock, so a table that cannot be written
refuses the start like the database (fatal), and no row is left.
"""

from __future__ import annotations

from sqlalchemy import Connection, func, select
from sqlalchemy.exc import SQLAlchemyError

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.tables import plan_refusals
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure

_PROBE_PROJECT_ID = "probe"
_PROBE_REASON = "probe"
_PROBE_STATUS = 0


class SqlAlchemyPlanRefusalLog:
    def __init__(self, database: SqliteDatabase, clock: Clock) -> None:
        self._database = database
        self._clock = clock

    def append(self, project_id: str, reason: str, http_status: int) -> None:
        with self._database.writer_lock, self._database.engine.begin() as connection:
            self._insert(connection, project_id, reason, http_status)

    def probe(self) -> ProbeResult:
        check = ProbeCheck("plan_refusal_log_unwritable", self._round_trip)
        return first_failure((check,), failing_errors=(SQLAlchemyError,))

    def _round_trip(self) -> bool:
        with self._database.writer_lock, self._database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                self._insert(connection, _PROBE_PROJECT_ID, _PROBE_REASON, _PROBE_STATUS)
                query = select(func.count()).where(plan_refusals.c.project_id == _PROBE_PROJECT_ID)
                return bool(connection.execute(query).scalar_one() == 1)
            finally:
                transaction.rollback()

    def _insert(self, connection: Connection, project_id: str, reason: str, http_status: int) -> None:
        connection.execute(
            plan_refusals.insert().values(
                created_at=self._clock.now(), project_id=project_id, reason=reason, http_status=http_status
            )
        )
