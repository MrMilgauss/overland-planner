"""PlanJobLog port (ADR-015 amendment DV-2, D93): one append-only `plan_job_log` row per job that reached its end.

The row holds the values of the job's `plan.job.finished` line (brief section 5 field table, kpi-contracts) plus its
start and end and `solver_wait_s`; fields owned by later slices are null, as in the line. It is written in its own
transaction under the single writer lock, after the run is stored and before the ending is published. Synchronous
refusals (422, 409, 503) create no job and so no row. The adapter adds `app_version`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from overland_planner.application.ports.probe import Probeable

PLAN_JOB_LOG_FIELDS = (
    "job_id",
    "project_id",
    "terminal_state",
    "plan_run_id",
    "items_included",
    "legs_total",
    "legs_new",
    "legs_cached",
    "points_new",
    "second_pass_pairs",
    "retried",
    "memo_hit",
    "ignore_memo",
    "stage_ms",
    "solver_solutions",
    "incumbents",
    "reproducible",
    "not_fully_optimised_reason",
    "unconfirmed_legs",
    "retraces",
    "solver_wait_s",
    "provider_id",
    "elapsed_ms",
    "error_class",
    "reason",
)


@dataclass(frozen=True)
class PlanJobLogEntry:
    """A job's row: `fields` are the job's `plan.job.finished` fields; a column the line lacks is null."""

    started_at: datetime
    ended_at: datetime
    fields: Mapping[str, object]

    def columns(self) -> dict[str, object]:
        return {
            **{name: self.fields.get(name) for name in PLAN_JOB_LOG_FIELDS},
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


class PlanJobLog(Probeable, Protocol):
    def append(self, entry: PlanJobLogEntry) -> None:
        """Write the row in its own transaction under the single writer lock; raises when it cannot be written."""
        ...
