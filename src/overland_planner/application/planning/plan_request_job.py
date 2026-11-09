"""The work of one plan job (US-02b, brief section 8): snapshot, legs, solve, store the numbered run.

Runs on the job's own thread, never the request's. The snapshot is read under the write lock (D123); no file pins
(D204). The lock is not held while the road map or the solver works. Run number and row commit in one transaction.
Solver-side outcomes all store a run (D122); an exception stores nothing, because the data folder may be going away.
Before anything is stored the guard judges the solver's order, then the assembled plan against the canonical files
(ADR-009), which are read outside any lock; a violation stores a Failed run with no fallback (ADR-015). The solve runs
holding the job's solver slot (D133) and no unit of work. Later slices add the snapping, ladder, memo, Stop and limits
to this sequence.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from overland_planner.application.catalog.facade import (
    InvalidCanonicalPointsFileError,
    canonical_file_sha256,
    parse_canonical_points_file,
)
from overland_planner.application.planning.plan_job_registry import PlanJobProgress, StoredRun
from overland_planner.application.planning.plan_run_queries import existing_snapshot
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.file_store import CanonicalPointsMissing, FileStore
from overland_planner.application.ports.plan_run_repository import NewPlanRun, PlanningUnitOfWork
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.application.ports.tour_solver import TourFound, TourOptimizerFailed, TourOutcome, TourSolver
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.planning.invariant_guard import (
    INVARIANT_VIOLATION_REASON,
    CanonicalFileEvidence,
    GuardViolation,
    InvariantGuard,
)
from overland_planner.domain.planning.plan_run import PlanStop, Totals
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
class _Finding:
    """The run a finished plan stores. `invariants` is what the guard said, `None` when no plan reached it."""

    stops: tuple[PlanStop, ...] = ()
    totals: Totals | None = None
    failure_reason: str | None = None
    invariants: str | None = None
    plan_run_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class PlanRequestJob:
    unit_of_work: Callable[[], PlanningUnitOfWork]
    legs: LegResolver
    solver: TourSolver
    budget: int
    clock: Clock
    event_log: EventLog
    files: FileStore

    def run(self, project_id: str, progress: PlanJobProgress) -> StoredRun:
        project = self._read(project_id)
        progress.enter("computing_legs")
        legs = self._resolve_legs(project.snapshot, progress)
        with progress.solver_slot():
            outcome = self._solve(project.snapshot, legs, progress)
        progress.enter("finalising")
        stored = self._finish(project, legs, outcome)
        if stored.reason is not None:
            progress.note(reason=stored.reason)
        return stored

    def _finish(self, project: _PlannedProject, legs: LegTable, outcome: TourOutcome) -> StoredRun:
        if isinstance(outcome, TourFound):
            return self._finish_found(project, legs, outcome)
        return self._store(project, _Finding(failure_reason=outcome.reason))

    def _finish_found(self, project: _PlannedProject, legs: LegTable, tour: TourFound) -> StoredRun:
        guard = InvariantGuard(project.snapshot, legs)
        broken_order = guard.check_order(tour.order)  # first: the assembler raises on an unknown id
        if broken_order is not None:
            return self._store_violation(project, broken_order)
        stops = PlanRunAssembler(project.snapshot, legs).assemble(tour.visited_item_ids)
        broken_plan = guard.check_plan(stops, self._canonical_files(project.snapshot))
        if broken_plan is not None:
            return self._store_violation(project, broken_plan)
        return self._store(project, _Finding(stops=stops, totals=Totals.of(stops), invariants="ok"))

    def _store_violation(self, project: _PlannedProject, violation: GuardViolation) -> StoredRun:
        finding = _Finding(failure_reason=INVARIANT_VIOLATION_REASON, invariants="violated")
        self.event_log.warning(
            "invariant.violation", plan_run_id=finding.plan_run_id, check=violation.check, detail=violation.detail
        )
        return self._store(project, finding)

    def _canonical_files(self, snapshot: ProjectSnapshot) -> dict[str, CanonicalFileEvidence]:
        """What is stored for each track, read by the snapshot's direction version (ADR-009 Amendment 1)."""
        tracks = (item for item in snapshot.visited_items() if isinstance(item, TrackItem))
        read = {track.id: self.files.read_canonical_points(track.id, track.direction_version) for track in tracks}
        return {
            track_id: _evidence_of(content)
            for track_id, content in read.items()
            if not isinstance(content, CanonicalPointsMissing)
        }

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

    def _store(self, project: _PlannedProject, finding: _Finding) -> StoredRun:
        with self.unit_of_work() as uow:
            run = self._new_run(project, finding, uow.plan_runs.next_number(project.id))
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
            invariants=finding.invariants,
        )
        return StoredRun(run.id, finding.failure_reason)

    def _new_run(self, project: _PlannedProject, finding: _Finding, number: int) -> NewPlanRun:
        return NewPlanRun(
            id=finding.plan_run_id,
            project_id=project.id,
            number=number,
            status="ready" if finding.failure_reason is None else "failed",
            failure_reason=finding.failure_reason,
            created_at=self.clock.now(),
            revision=project.stamp.revision,
            provider_id=self.legs.provider_id,
            objective=project.stamp.objective,
            inputs=self._inputs(project.snapshot),
            stops=finding.stops,
            totals=finding.totals,
            report=PlanRunAssembler.report(finding.failure_reason),
        )

    def _inputs(self, snapshot: ProjectSnapshot) -> dict[str, object]:
        return {
            "start_item_id": snapshot.start_item_id,
            "end_item_id": snapshot.end_item_id,
            "included_item_ids": [item.id for item in snapshot.visited_items()],
            "solver_budget": self.budget,
        }


def _evidence_of(content: bytes) -> CanonicalFileEvidence:
    sha256 = canonical_file_sha256(content)
    try:
        points = parse_canonical_points_file(content)
    except InvalidCanonicalPointsFileError:
        points = ()
    if not points:
        return CanonicalFileEvidence(sha256, 0, None, None)
    return CanonicalFileEvidence(sha256, len(points), points[0].coordinate, points[-1].coordinate)
