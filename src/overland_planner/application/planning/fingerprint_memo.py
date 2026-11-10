"""The fingerprint memo (ADR-014 section 5, FR-5.6): identical solver inputs reuse the order of an earlier plan.

The source is the latest ready run of the same project with the inputs' fingerprint; its order is the item ids of its
stored itinerary. A Failed run, and a run stored before the memo (fingerprint null), is never a source. The plan job
still judges a reused order with the guard and recomputes the totals (ADR-009, ADR-014). The source is returned whole
(its id, number, order and run flags): a memo hit names it and inherits its `reproducible` flag and its "not fully
optimised" label (ADR-014 section 5, D74). `solver_identity` is the `identity` of the wired `TourSolver`, passed in by
the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.application.ports.plan_run_repository import PlanningUnitOfWork
from overland_planner.domain.planning.fingerprint import Fingerprint, SolveSettings
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.run_messages import NotFullyOptimised
from overland_planner.domain.planning.solver_model_builder import TourModel


@dataclass(frozen=True)
class MemoSource:
    """The ready run a memo hit reuses: its id and number, its order of item ids and its run flags."""

    plan_run_id: str
    number: int
    order: tuple[str, ...]
    reproducible: bool
    not_fully_optimised: NotFullyOptimised | None


@dataclass(frozen=True)
class FingerprintMemo:
    solver_identity: str

    def fingerprint(
        self, snapshot: ProjectSnapshot, model: TourModel, *, objective: str, provider_id: str, budget: int
    ) -> Fingerprint:
        settings = SolveSettings(objective, provider_id, budget, self.solver_identity)
        return Fingerprint.of(snapshot, model, settings)

    def source(self, uow: PlanningUnitOfWork, project_id: str, fingerprint: Fingerprint) -> MemoSource | None:
        """The memo source, or `None` when the project has no ready run with this fingerprint."""
        source = uow.plan_runs.latest_ready(project_id, fingerprint.value)
        if source is None or not source.stops:
            return None
        order = tuple(stop.item_id for stop in source.stops)
        return MemoSource(source.id, source.number, order, source.reproducible, source.not_fully_optimised)
