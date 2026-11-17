"""`DiagnosticsReader` on SQLAlchemy Core (DV-3, kpi-contracts `diagnostics_endpoint`): read-only queries.

Every read opens its own connection and never takes the single writer lock: SQLite WAL lets it read beside a writer.
Job rows come with their project's name (NULL once the project is gone, the log has no foreign key). SQLite gives the
stored UTC timestamps back naive, so they are read as UTC. The probe runs the job query on an empty window.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import RowMapping, exists, select
from sqlalchemy.exc import SQLAlchemyError

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.tables import plan_job_log, plan_refusals, plan_runs, projects
from overland_planner.application.ports.diagnostics_reader import JobLogRow, PlanRunRow, RefusalRow
from overland_planner.application.ports.probe import ProbeCheck, ProbeResult, first_failure

_PROBE_SINCE = datetime(9999, 1, 1, tzinfo=UTC)
_JOB_QUERY = select(
    plan_job_log.c.project_id,
    projects.c.name.label("project_name"),
    plan_job_log.c.started_at,
    plan_job_log.c.terminal_state,
    plan_job_log.c.elapsed_ms,
    plan_job_log.c.memo_hit,
    plan_job_log.c.items_included,
    plan_job_log.c.stage_ms,
    plan_job_log.c.retried,
    plan_job_log.c.second_pass_pairs,
).select_from(plan_job_log.outerjoin(projects, projects.c.id == plan_job_log.c.project_id))
_RUN_QUERY = select(
    plan_runs.c.project_id,
    plan_runs.c.created_at,
    plan_runs.c.status,
    plan_runs.c.failure_reason,
    plan_runs.c.inputs,
    plan_runs.c.itinerary,
).order_by(plan_runs.c.created_at)
_REFUSAL_QUERY = select(plan_refusals.c.project_id, plan_refusals.c.reason, plan_refusals.c.created_at)


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _job(row: RowMapping) -> JobLogRow:
    values: dict[str, Any] = dict(row)
    values["started_at"] = _utc(row["started_at"])
    values["memo_hit"] = bool(row["memo_hit"])
    return JobLogRow(**values)


def _run(row: RowMapping) -> PlanRunRow:
    stops = (row["itinerary"] or {}).get("stops", [])
    return PlanRunRow(
        project_id=row["project_id"],
        created_at=_utc(row["created_at"]),
        status=row["status"],
        failure_reason=row["failure_reason"],
        included_item_ids=tuple(row["inputs"].get("included_item_ids", [])),
        stop_item_ids=tuple(stop["item_id"] for stop in stops),
    )


def _refusal(row: RowMapping) -> RefusalRow:
    return RefusalRow(row["project_id"], row["reason"], _utc(row["created_at"]))


class SqlAlchemyDiagnosticsReader:
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def project_exists(self, project_id: str) -> bool:
        with self._database.engine.connect() as connection:
            return bool(connection.execute(select(exists().where(projects.c.id == project_id))).scalar_one())

    def jobs_since(self, since: datetime) -> Sequence[JobLogRow]:
        query = _JOB_QUERY.where(plan_job_log.c.started_at >= _utc(since)).order_by(plan_job_log.c.started_at)
        with self._database.engine.connect() as connection:
            return [_job(row) for row in connection.execute(query).mappings()]

    def plan_runs(self) -> Sequence[PlanRunRow]:
        with self._database.engine.connect() as connection:
            return [_run(row) for row in connection.execute(_RUN_QUERY).mappings()]

    def refusals_since(self, since: datetime) -> Sequence[RefusalRow]:
        query = _REFUSAL_QUERY.where(plan_refusals.c.created_at >= _utc(since)).order_by(plan_refusals.c.created_at)
        with self._database.engine.connect() as connection:
            return [_refusal(row) for row in connection.execute(query).mappings()]

    def probe(self) -> ProbeResult:
        check = ProbeCheck("diagnostics_unreadable", lambda: self.jobs_since(_PROBE_SINCE) == [])
        return first_failure((check,), failing_errors=(SQLAlchemyError,))
