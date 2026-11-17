"""DiagnosticsReader port (DV-3, kpi-contracts `diagnostics_endpoint`): the read-only rows of `GET /api/diagnostics`.

The adapter reads `plan_job_log` (with the project's name, null when the project is gone), `plan_runs` and
`plan_refusals`; it never
writes and never takes the single writer lock (SQLite WAL readers). The arithmetic (percentiles, bands, medians) is
the use case's (`application/platform/diagnostics_service.py`). The probe is read-only: one query on an empty window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from overland_planner.application.ports.probe import Probeable


@dataclass(frozen=True)
class JobLogRow:
    """One `plan_job_log` row as the diagnostics need it; `stage_ms` holds the stages the job recorded."""

    project_id: str
    project_name: str | None
    started_at: datetime
    terminal_state: str
    elapsed_ms: int
    memo_hit: bool
    items_included: int | None = None
    stage_ms: Mapping[str, int] | None = None
    retried: bool | None = None
    second_pass_pairs: int | None = None


@dataclass(frozen=True)
class PlanRunRow:
    """One plan run: its outcome, the item ids it was asked to visit (`inputs.included_item_ids`) and its stops'."""

    project_id: str
    created_at: datetime
    status: str
    failure_reason: str | None
    included_item_ids: tuple[str, ...]
    stop_item_ids: tuple[str, ...]


@dataclass(frozen=True)
class RefusalRow:
    """One `plan_refusals` row as the diagnostics need it: the project, the refusal's reason and when it was made."""

    project_id: str
    reason: str
    created_at: datetime


class DiagnosticsReader(Probeable, Protocol):
    def project_exists(self, project_id: str) -> bool: ...

    def jobs_since(self, since: datetime) -> Sequence[JobLogRow]:
        """Every job row that started at or after `since`."""
        ...

    def plan_runs(self) -> Sequence[PlanRunRow]:
        """Every plan run, all time (K2 and K3 are counted all time and over the window)."""
        ...

    def refusals_since(self, since: datetime) -> Sequence[RefusalRow]:
        """Every refused plan request made at or after `since` (G4)."""
        ...
