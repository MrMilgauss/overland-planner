"""The work of one plan job (US-02b, brief section 8): snapshot, legs, solve, store the numbered run.

Runs on the job's own thread, never the request's. The snapshot is read under the write lock (D123); no file pins
(D204). The lock is not held while the road map or the solver works. Run number and row commit in one transaction.
Solver-side outcomes all store a run (D122); an exception stores nothing, because the data folder may be going away.
Later slices add the snapping, ladder, memo, guard, Stop and limits to this sequence.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from overland_planner.application.planning.plan_job_registry import PlanJobProgress, StoredRun
from overland_planner.application.planning.plan_run_queries import existing_snapshot
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.plan_run_repository import NewPlanRun, PlanningUnitOfWork
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.application.ports.tour_solver import TourFound, TourOptimizerFailed, TourOutcome, TourSolver
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.plan_run_assembler import PlanRunAssembler
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from overland_planner.domain.routing.road_leg import LegTable


@dataclass(frozen=True)
class _PlannedProject:
    id: str
    snapshot: ProjectSnapshot
    stamp: ProjectStamp


@dataclass(frozen=True)
class PlanRequestJob:
    unit_of_work: Callable[[], PlanningUnitOfWork]
    legs: LegResolver
    solver: TourSolver
    budget: int
    clock: Clock
    event_log: EventLog

    def run(self, project_id: str, progress: PlanJobProgress) -> StoredRun:
        project = self._read(project_id)
        progress.enter("computing_legs")
        legs = self._resolve_legs(project.snapshot, progress)
        progress.enter("solving")
        outcome = self._solve(project.snapshot, legs, progress)
        progress.enter("finalising")
        if isinstance(outcome, TourFound):
            stops = PlanRunAssembler(project.snapshot, legs).assemble(outcome.visited_item_ids)
            return self._store(project, stops, None)
        return self._store(project, (), outcome.reason)

    def _read(self, project_id: str) -> _PlannedProject:
        with self.unit_of_work() as uow:
            snapshot = existing_snapshot(uow, project_id)
            return _PlannedProject(project_id, snapshot, uow.project_snapshots.stamp(project_id))

    def _resolve_legs(self, snapshot: ProjectSnapshot, progress: PlanJobProgress) -> LegTable:
        pairs = SolverModelBuilder(snapshot).required_pairs()
        legs = self.legs.resolve(pairs)
        progress.note(legs_total=len(set(pairs)), provider_id=self.legs.provider_id)
        return legs

    def _solve(self, snapshot: ProjectSnapshot, legs: LegTable, progress: PlanJobProgress) -> TourOutcome:
        model = SolverModelBuilder(snapshot).build(legs)
        progress.note(items_included=len(set(model.node_item_ids)))
        outcome = self.solver.solve(model, self.budget)
        if isinstance(outcome, TourOptimizerFailed):
            progress.note(exit_code=outcome.exit_code, signal=outcome.signal)
        return outcome

    def _store(self, project: _PlannedProject, stops: tuple[PlanStop, ...], failure_reason: str | None) -> StoredRun:
        with self.unit_of_work() as uow:
            run = self._new_run(project, stops, failure_reason, uow.plan_runs.next_number(project.id))
            uow.plan_runs.add(run)
            uow.commit()
        self.event_log.info(
            "plan.run.completed",
            plan_run_id=run.id,
            number=run.number,
            status=run.status,
            failure_reason=run.failure_reason,
            report_items=None,
            project_items=len(project.snapshot.items),
            invariants=None,
        )
        return StoredRun(run.id, failure_reason)

    def _new_run(
        self, project: _PlannedProject, stops: tuple[PlanStop, ...], failure_reason: str | None, number: int
    ) -> NewPlanRun:
        return NewPlanRun(
            id=uuid.uuid4().hex,
            project_id=project.id,
            number=number,
            status="ready" if failure_reason is None else "failed",
            failure_reason=failure_reason,
            created_at=self.clock.now(),
            revision=project.stamp.revision,
            provider_id=self.legs.provider_id,
            objective=project.stamp.objective,
            inputs=self._inputs(project.snapshot),
            stops=stops,
        )

    def _inputs(self, snapshot: ProjectSnapshot) -> dict[str, object]:
        return {
            "start_item_id": snapshot.start_item_id,
            "end_item_id": snapshot.end_item_id,
            "included_item_ids": [item.id for item in snapshot.visited_items()],
            "solver_budget": self.budget,
        }
