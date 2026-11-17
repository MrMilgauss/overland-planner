"""PlanRefusalLog port (ADR-013 Amendment 4, D248): one append-only `plan_refusals` row per refused plan request.

The row holds the project, the refusal's reason (the `plan.job.refused` line's) and its HTTP status; the adapter adds
the id and the time (the `Clock` port). The diagnostics count the engine's reasons from it (kpi-contracts G4).
"""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.probe import Probeable


class PlanRefusalLog(Probeable, Protocol):
    def append(self, project_id: str, reason: str, http_status: int) -> None:
        """Write the row in its own transaction under the single writer lock; raises when it cannot be written."""
        ...
