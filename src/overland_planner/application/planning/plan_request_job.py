"""The work of one plan job (US-02b, brief section 8): snapshot, legs, solve, store the numbered run.

Runs on the job's own thread, never the request's. The snapshot is read under the write lock (D123); no file pins
(D204). The lock is not held while the road map or the solver works. Run number and row commit in one transaction.
Solver-side outcomes all store a run (D122); an exception stores nothing, because the data folder may be going away.
Before anything is stored the guard judges the solver's order, then the assembled plan against the canonical files
(ADR-009), which are read outside any lock; a violation stores a Failed run with no fallback (ADR-015). The solve runs
holding the job's solver slot (D133) and no unit of work. With a fingerprint memo (ADR-014 section 5) the model's
fingerprint is stored on every run, and a ready run of the project with it gives the order without the solver; the
totals are recomputed. Later slices add the snapping, ladder and Stop to this sequence.

The solve is handed its deadlines (ADR-014 section 2, D58): the job's `SolveLimits` from the start of the job's work on
the `Clock` port, so the road legs and the wait for the solver slot count. A Failed `timeout` run and its job's end say
so in words with the run's number (D151, `run_messages`).

The solver streams its incumbents to the job: the poll shows the last one with `found_at_s`, stamped on receipt by the
`Clock` port's monotonic time from the start of the job's work, and the job's line counts them (`incumbents`). How a
found tour's search ended sets the run's flags: `reproducible` only when the budget ended it (D42), and
`not_fully_optimised` names any other ending of a ready run (D122); the job's line carries both.

Each stage notes its whole milliseconds, truncated, by the `Clock` port's monotonic time, as it ends (`stage_ms`,
ADR-015 DV-2, K5): `snapshot`, `matrix` (the road legs), `reach_model` (the model, its fingerprint and the memo lookup),
`solve` (the solver from its start to its end, child spawn included, and not the wait for the slot; none on a memo hit)
and `guard_persist` (guard, assemble, store). Truncating keeps their sum within the job's elapsed time.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

from overland_planner.application.catalog.facade import (
    InvalidCanonicalPointsFileError,
    canonical_file_sha256,
    parse_canonical_points_file,
)
from overland_planner.application.planning.fingerprint_memo import FingerprintMemo
from overland_planner.application.planning.plan_job_registry import PlanJobProgress, StoredRun
from overland_planner.application.planning.plan_run_queries import existing_snapshot
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.file_store import CanonicalPointsMissing, FileStore
from overland_planner.application.ports.plan_run_repository import NewPlanRun, PlanningUnitOfWork
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.application.ports.tour_solver import (
    Incumbent,
    SolveLimits,
    TourFound,
    TourOptimizerFailed,
    TourOutcome,
    TourSolver,
)
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
from overland_planner.domain.planning.run_messages import NotFullyOptimised, job_message
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder, TourModel
from overland_planner.domain.routing.road_leg import LegTable

_MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True)
class _PlannedProject:
    id: str
    snapshot: ProjectSnapshot
    stamp: ProjectStamp
    ignore_memo: bool
    fingerprint: str | None = None
    memo_hit: bool = False


@dataclass(frozen=True)
class _Finding:
    """The run a finished plan stores. `invariants` is what the guard said, `None` when no plan reached it."""

    stops: tuple[PlanStop, ...] = ()
    totals: Totals | None = None
    failure_reason: str | None = None
    invariants: str | None = None
    reproducible: bool = True
    not_fully_optimised: NotFullyOptimised | None = None
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
    memo: FingerprintMemo | None = None
    limits: SolveLimits = field(default_factory=SolveLimits)

    def run(self, project_id: str, progress: PlanJobProgress, *, ignore_memo: bool = False) -> StoredRun:
        """With a memo, a ready run of the project with the inputs' fingerprint gives the order and the solver is not
        asked, unless `ignore_memo`; the guard judges a reused order like a solved one."""
        started_s = self.clock.monotonic()
        stages = _Stages(self.clock, progress)
        with stages.timing("snapshot"):
            project = self._read(project_id, ignore_memo)
        progress.enter("computing_legs")
        with stages.timing("matrix"):
            legs = self._resolve_legs(project.snapshot, progress)
        with stages.timing("reach_model"):
            model = SolverModelBuilder(project.snapshot).build(legs)
            progress.note(items_included=len(set(model.node_item_ids)))
            project, reused = self._recall(project, model)
        if reused is not None:
            progress.note(memo_hit=True)
            outcome: TourOutcome = TourFound(order=reused)
        else:
            with progress.solver_slot(), stages.timing("solve"):
                outcome = self._solve(model, progress, started_s)
        progress.enter("finalising")
        with stages.timing("guard_persist"):
            stored = self._finish(project, legs, outcome)
        progress.note(reproducible=stored.reproducible, not_fully_optimised_reason=stored.not_fully_optimised)
        if stored.reason is not None:
            progress.note(reason=stored.reason)
        return stored

    def _finish(self, project: _PlannedProject, legs: LegTable, outcome: TourOutcome) -> StoredRun:
        if isinstance(outcome, TourFound):
            return self._finish_found(project, legs, outcome)
        return self._store(project, _Finding(failure_reason=outcome.reason, reproducible=outcome.reproducible))

    def _finish_found(self, project: _PlannedProject, legs: LegTable, tour: TourFound) -> StoredRun:
        guard = InvariantGuard(project.snapshot, legs)
        broken_order = guard.check_order(tour.order)  # first: the assembler raises on an unknown id
        if broken_order is not None:
            return self._store_violation(project, broken_order, tour.reproducible)
        stops = PlanRunAssembler(project.snapshot, legs).assemble(tour.visited_item_ids)
        broken_plan = guard.check_plan(stops, self._canonical_files(project.snapshot))
        if broken_plan is not None:
            return self._store_violation(project, broken_plan, tour.reproducible)
        finding = _Finding(
            stops=stops,
            totals=Totals.of(stops),
            invariants="ok",
            reproducible=tour.reproducible,
            not_fully_optimised=tour.not_fully_optimised,
        )
        return self._store(project, finding)

    def _store_violation(self, project: _PlannedProject, violation: GuardViolation, reproducible: bool) -> StoredRun:
        """No fallback to an earlier incumbent (ADR-015): the chosen order broke a rule, so the run is Failed."""
        finding = _Finding(failure_reason=INVARIANT_VIOLATION_REASON, invariants="violated", reproducible=reproducible)
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

    def _read(self, project_id: str, ignore_memo: bool) -> _PlannedProject:
        with self.unit_of_work() as uow:
            snapshot = existing_snapshot(uow, project_id)
            return _PlannedProject(project_id, snapshot, uow.project_snapshots.stamp(project_id), ignore_memo)

    def _resolve_legs(self, snapshot: ProjectSnapshot, progress: PlanJobProgress) -> LegTable:
        pairs = SolverModelBuilder(snapshot).required_pairs()
        legs = self.legs.resolve(pairs)
        progress.note(legs_total=len(set(pairs)), provider_id=self.legs.provider_id)
        return legs

    def _recall(self, project: _PlannedProject, model: TourModel) -> tuple[_PlannedProject, tuple[str, ...] | None]:
        """The project with its fingerprint and memo hit, and the reused order, `None` when the solver is asked."""
        if self.memo is None:
            return project, None
        fingerprint = self.memo.fingerprint(
            project.snapshot,
            model,
            objective=project.stamp.objective,
            provider_id=self.legs.provider_id,
            budget=self.budget,
        )
        reused = None
        if not project.ignore_memo:
            with self.unit_of_work() as uow:
                reused = self.memo.reused_order(uow, project.id, fingerprint)
        return replace(project, fingerprint=fingerprint.value, memo_hit=reused is not None), reused

    def _solve(self, model: TourModel, progress: PlanJobProgress, started_s: float) -> TourOutcome:
        incumbents = _Incumbents(self.clock, progress, started_s)
        deadlines = self.limits.from_start(self.clock, started_s)
        outcome = self.solver.solve(model, self.budget, incumbents.found, deadlines=deadlines)
        progress.note(incumbents=incumbents.count)
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
            memo_hit=project.memo_hit,
            ignore_memo=project.ignore_memo,
        )
        message = job_message(finding.failure_reason, run.number)
        return StoredRun(run.id, finding.failure_reason, finding.reproducible, finding.not_fully_optimised, message)

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
            fingerprint=project.fingerprint,
            memo_hit=project.memo_hit,
            reproducible=finding.reproducible,
            not_fully_optimised=finding.not_fully_optimised,
        )

    def _inputs(self, snapshot: ProjectSnapshot) -> dict[str, object]:
        return {
            "start_item_id": snapshot.start_item_id,
            "end_item_id": snapshot.end_item_id,
            "included_item_ids": [item.id for item in snapshot.visited_items()],
            "solver_budget": self.budget,
        }


class _Incumbents:
    """The incumbents a solve streamed, on the solving thread: the poll shows the last, the job's line counts them."""

    def __init__(self, clock: Clock, progress: PlanJobProgress, started_s: float) -> None:
        self._clock = clock
        self._progress = progress
        self._started_s = started_s
        self.count = 0

    def found(self, incumbent: Incumbent) -> None:
        self.count += 1
        shown = {
            "unconfirmed_legs": incumbent.unconfirmed_legs,
            "retraces": incumbent.retraces,
            "objective": incumbent.objective,
            "found_at_s": self._clock.monotonic() - self._started_s,
        }
        self._progress.note(incumbents=self.count, incumbent=shown)


class _Stages:
    """The whole milliseconds of each stage that ended, noted as `stage_ms` on the job's progress."""

    def __init__(self, clock: Clock, progress: PlanJobProgress) -> None:
        self._clock = clock
        self._progress = progress
        self._ms: dict[str, int] = {}

    @contextmanager
    def timing(self, stage: str) -> Iterator[None]:
        began_s = self._clock.monotonic()
        yield
        self._ms[stage] = int((self._clock.monotonic() - began_s) * _MILLISECONDS_PER_SECOND)
        self._progress.note(stage_ms=dict(self._ms))


def _evidence_of(content: bytes) -> CanonicalFileEvidence:
    sha256 = canonical_file_sha256(content)
    try:
        points = parse_canonical_points_file(content)
    except InvalidCanonicalPointsFileError:
        points = ()
    if not points:
        return CanonicalFileEvidence(sha256, 0, None, None)
    return CanonicalFileEvidence(sha256, len(points), points[0].coordinate, points[-1].coordinate)
