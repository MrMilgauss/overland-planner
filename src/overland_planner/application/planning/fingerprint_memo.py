"""The fingerprint memo (ADR-014 section 5, FR-5.6): identical solver inputs reuse the order of an earlier plan.

The source is the latest ready run of the same project with the inputs' fingerprint; its order is the item ids of its
stored itinerary. A Failed run, and a run stored before the memo (fingerprint null), is never a source. The plan job
still judges a reused order with the guard and recomputes the totals (ADR-009, ADR-014). A memo source made by a stopped
or time-limited run keeps its label (D74), which arrives with slice 03. `solver_identity` is the constant the solver
adapter publishes, passed in by the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.application.ports.plan_run_repository import PlanningUnitOfWork
from overland_planner.domain.planning.fingerprint import Fingerprint, SolveSettings
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import TourModel


@dataclass(frozen=True)
class FingerprintMemo:
    solver_identity: str

    def fingerprint(
        self, snapshot: ProjectSnapshot, model: TourModel, *, objective: str, provider_id: str, budget: int
    ) -> Fingerprint:
        settings = SolveSettings(objective, provider_id, budget, self.solver_identity)
        return Fingerprint.of(snapshot, model, settings)

    def reused_order(
        self, uow: PlanningUnitOfWork, project_id: str, fingerprint: Fingerprint
    ) -> tuple[str, ...] | None:
        """The order of the memo source, or `None` when the project has no ready run with this fingerprint."""
        source = uow.plan_runs.latest_ready(project_id, fingerprint.value)
        if source is None or not source.stops:
            return None
        return tuple(stop.item_id for stop in source.stops)
