"""The work of one plan job (US-02b, brief section 8): snapshot, legs, solve, store the numbered run.

Runs on the job's own thread, never the request's. The snapshot is read under the write lock (D123); no file pins
(D204). The lock is not held while the road map or the solver works. Run number and row commit in one transaction.
Solver-side outcomes all store a run (D122); an exception stores nothing, because the data folder may be going away.
Before anything is stored the guard judges the solver's order, then the assembled plan against the canonical files
(ADR-009), which are read outside any lock; a violation stores a Failed run with no fallback (ADR-015). For each track
the plan retraces, the file read by version also gives the hash of its points reversed, which the assembler writes on
the retrace row and the guard checks (ADR-009 Amendment 2). The solve runs
holding the job's solver slot (D133) and no unit of work. With a fingerprint memo (ADR-014 section 5) the model's
fingerprint is stored on every run, and a ready run of the project with it gives the order without the solver; the
totals are recomputed. Later slices add the snapping and the ladder to this sequence.

Stop reaches the solve through the port's stop signal (brief section 6), the one the job's solver slot answers: a
progress without one (`None`) hands the solve one that is never set. A stopped solve stores the last incumbent
labelled `stopped`, not reproducible, or a Failed `stopped` run whose words say so (ADR-015, D60, D122).

The solve is handed its deadlines (ADR-014 section 2, D58): the job's `SolveLimits` from the start of the job's work on
the `Clock` port, so the road legs and the wait for the solver slot count. The work starts on its own thread under 1 ms
after the registry started the job, from whose start the registry's watch and slot wait count the feasibility limit;
`work_started_s` names the work's start. A Failed `timeout` run and its job's end say so in words with the run's
number (D151, `run_messages`).

The solver streams its incumbents to the job: the poll shows the last one with `found_at_s`, stamped on receipt by the
`Clock` port's monotonic time from the start of the job's work, and the job's line counts them (`incumbents`). How a
found tour's search ended sets the run's flags: `reproducible` only when the budget ended it (D42), and
`not_fully_optimised` names any other ending of a ready run (D122); the job's line carries both.

Before the memo lookup and the solver slot, the model's arcs are checked (`unreachable_item_ids`, ADR-016 section 3):
an Included item with no arc in, no arc out, no path from the Start or to the End fails the run as `unreachable`, its
report naming each such item (`report.items`), and the solver is never asked (07-05, stage `reach_model`). The guard
re-derives the claim from the leg table first; a claim it does not confirm stores an invariant violation instead.

Each stage notes its whole milliseconds, truncated, by the `Clock` port's monotonic time, as it ends (`stage_ms`,
ADR-015 DV-2, K5): `snapshot`, `matrix` (the road legs), `reach_model` (the model, its fingerprint and the memo lookup),
`solve` (the solver from its start to its end, child spawn included, and not the wait for the slot; none on a memo hit)
and `guard_persist` (guard, assemble, store). Truncating keeps their sum within the job's elapsed time.

The road legs come from the leg resolver, which keeps those found for the process's life (06-09): the job notes
`legs_cached` and `legs_new` as they arrive, and `legs_total` once the look-up is done. After the first pass it asks
the second pass, the retrace pairs of the arcs whose first pair has no road (ADR-017 section 2), and notes how many
they were (`second_pass_pairs`, only when there was one); they join `legs_total`. A job its registry ended
during the look-up raises that ending at its next fact or state, so a late road-map answer stores no run.

Every run stores its `run_time_ms`, from the start of the job's work to the run stored, by the `Clock` port's monotonic
time, rounded (06-10). A memo hit stores the run it reused (`memo_source_run_id`) and inherits its label and
`reproducible` flag (ADR-014 section 5, D74). Once the snapshot is read the job notes its `notices` for the poll: the
large-project notice above 60 Included items other than the anchors (D146).
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
    reversed_points_sha256,
)
from overland_planner.application.planning.fingerprint_memo import FingerprintMemo, MemoSource
from overland_planner.application.planning.plan_job_registry import PlanJobProgress, StoredRun
from overland_planner.application.planning.plan_run_queries import existing_snapshot
from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.file_store import CanonicalPointsMissing, FileStore
from overland_planner.application.ports.plan_run_repository import NewPlanRun, PlanningUnitOfWork
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.application.ports.tour_solver import (
    NEVER_STOPPED,
    Incumbent,
    SolveLimits,
    StopSignal,
    TourFound,
    TourOptimizerFailed,
    TourOutcome,
    TourSolver,
)
from overland_planner.application.routing.facade import LegResolver, LegsFound
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
from overland_planner.domain.planning.reachability import unreachable_item_ids
from overland_planner.domain.planning.run_messages import (
    UNREACHABLE,
    NotFullyOptimised,
    job_message,
    project_notices,
)
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder, TourModel
from overland_planner.domain.routing.road_leg import LegTable

_MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True)
class _PlannedProject:
    id: str
    snapshot: ProjectSnapshot
    stamp: ProjectStamp
    ignore_memo: bool
    work_started_s: float
    fingerprint: str | None = None
    memo_source: MemoSource | None = None

    @property
    def memo_hit(self) -> bool:
        return self.memo_source is not None


@dataclass(frozen=True)
class _Finding:
    """The run a finished plan stores. `invariants` is what the guard said, `None` when no plan reached it."""

    stops: tuple[PlanStop, ...] = ()
    totals: Totals | None = None
    failure_reason: str | None = None
    invariants: str | None = None
    reproducible: bool = True
    not_fully_optimised: NotFullyOptimised | None = None
    report_items: tuple[str, ...] = ()
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
        work_started_s = self.clock.monotonic()
        stages = _Stages(self.clock, progress)
        with stages.timing("snapshot"):
            project = self._read(project_id, ignore_memo, work_started_s)
        progress.note(notices=project_notices(len(project.snapshot.visited_items())))
        progress.enter("computing_legs")
        with stages.timing("matrix"):
            legs = self._resolve_legs(project.snapshot, progress)
        with stages.timing("reach_model"):
            model = SolverModelBuilder(project.snapshot).build(legs)
            progress.note(items_included=len(set(model.node_item_ids)))
            cut_off = unreachable_item_ids(model)
            reused = None
            if not cut_off:
                project, reused = self._recall(project, model)
        if cut_off:
            return self._end_unreachable(project, legs, cut_off, progress, stages)
        if reused is not None:
            progress.note(memo_hit=True)
            outcome: TourOutcome = reused
        else:
            with progress.solver_slot() as stop, stages.timing("solve"):
                outcome = self._solve(model, progress, work_started_s, stop or NEVER_STOPPED)
        progress.enter("finalising")
        with stages.timing("guard_persist"):
            stored = self._finish(project, legs, outcome)
        return _ended(progress, stored)

    def _end_unreachable(
        self,
        project: _PlannedProject,
        legs: LegTable,
        cut_off: tuple[str, ...],
        progress: PlanJobProgress,
        stages: _Stages,
    ) -> StoredRun:
        """The run fails before the memo and the solver slot, naming each item the arcs cut off in words, once the
        guard has re-derived the claim from the leg table (ADR-009 Amendment 1)."""
        progress.enter("finalising")
        names = tuple(project.snapshot.item(item_id).name for item_id in cut_off)
        with stages.timing("guard_persist"):
            wrong_claim = InvariantGuard(project.snapshot, legs).check_unreachable(cut_off)
            if wrong_claim is not None:
                stored = self._store_violation(project, wrong_claim, reproducible=True)
            else:
                stored = self._store(project, _Finding(failure_reason=UNREACHABLE, report_items=names))
        return _ended(progress, stored)

    def _finish(self, project: _PlannedProject, legs: LegTable, outcome: TourOutcome) -> StoredRun:
        if isinstance(outcome, TourFound):
            return self._finish_found(project, legs, outcome)
        return self._store(project, _Finding(failure_reason=outcome.reason, reproducible=outcome.reproducible))

    def _finish_found(self, project: _PlannedProject, legs: LegTable, tour: TourFound) -> StoredRun:
        guard = InvariantGuard(project.snapshot, legs)
        broken_order = guard.check_order(tour.order)  # first: the assembler raises on an unknown id
        if broken_order is not None:
            return self._store_violation(project, broken_order, tour.reproducible)
        assembler = PlanRunAssembler(project.snapshot, legs)
        retraced = {stop.item_id for stop in assembler.assemble(tour.visited_item_ids) if stop.kind == "retrace"}
        files = self._canonical_files(project.snapshot, retraced)
        stops = assembler.assemble(tour.visited_item_ids, _retrace_hashes(files, retraced))
        broken_plan = guard.check_plan(stops, files)
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

    def _canonical_files(self, snapshot: ProjectSnapshot, retraced: set[str]) -> dict[str, CanonicalFileEvidence]:
        """What is stored for each track, read by the snapshot's direction version (ADR-009 Amendment 1), with the
        reversed points' hash for the `retraced` ones only (Amendment 2)."""
        tracks = (item for item in snapshot.visited_items() if isinstance(item, TrackItem))
        read = {track.id: self.files.read_canonical_points(track.id, track.direction_version) for track in tracks}
        return {
            track_id: _evidence_of(content, track_id in retraced)
            for track_id, content in read.items()
            if not isinstance(content, CanonicalPointsMissing)
        }

    def _read(self, project_id: str, ignore_memo: bool, work_started_s: float) -> _PlannedProject:
        with self.unit_of_work() as uow:
            snapshot = existing_snapshot(uow, project_id)
            stamp = uow.project_snapshots.stamp(project_id)
            return _PlannedProject(project_id, snapshot, stamp, ignore_memo, work_started_s)

    def _resolve_legs(self, snapshot: ProjectSnapshot, progress: PlanJobProgress) -> LegTable:
        """The legs found so far are noted as they arrive, the cached ones before any road-map call (06-09). The second
        pass asks the retrace pairs once the first has come back (ADR-017 section 2); its pairs join the job's total
        and its counts the first pass's, so that `new + cached = total` at the end."""
        builder = SolverModelBuilder(snapshot)
        pairs = builder.required_pairs()
        first_found = LegsFound(0, 0, 0)

        def first_pass_heard(found: LegsFound) -> None:
            nonlocal first_found
            first_found = found
            _note_legs(progress, found)

        legs = self.legs.resolve(pairs, first_pass_heard)
        known = set(pairs)
        second = tuple(pair for pair in builder.retrace_pairs(legs) if pair not in known)
        if second:
            legs = legs.merged_with(
                self.legs.resolve(second, lambda found: _note_legs(progress, _added(first_found, found)))
            )
            progress.note(second_pass_pairs=len(second))
        progress.note(legs_total=len(known) + len(second), provider_id=self.legs.provider_id)
        return legs

    def _recall(self, project: _PlannedProject, model: TourModel) -> tuple[_PlannedProject, TourFound | None]:
        """The project with its fingerprint and memo source, and the reused tour, `None` when the solver is asked. The
        reused tour ends as its source's search did, so the run inherits its label and `reproducible` flag (D74)."""
        if self.memo is None:
            return project, None
        fingerprint = self.memo.fingerprint(
            project.snapshot,
            model,
            objective=project.stamp.objective,
            provider_id=self.legs.provider_id,
            budget=self.budget,
        )
        source = None
        if not project.ignore_memo:
            with self.unit_of_work() as uow:
                source = self.memo.source(uow, project.id, fingerprint)
        recalled = replace(project, fingerprint=fingerprint.value, memo_source=source)
        return recalled, None if source is None else TourFound(source.order, source.not_fully_optimised or "budget")

    def _solve(
        self, model: TourModel, progress: PlanJobProgress, work_started_s: float, stop: StopSignal
    ) -> TourOutcome:
        incumbents = _Incumbents(self.clock, progress, work_started_s)
        deadlines = self.limits.from_start(self.clock, work_started_s)
        outcome = self.solver.solve(model, self.budget, incumbents.found, deadlines=deadlines, stop=stop)
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
        message = job_message(finding.failure_reason, run.number, finding.report_items)
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
            report=PlanRunAssembler.report(finding.failure_reason, finding.report_items),
            fingerprint=project.fingerprint,
            memo_hit=project.memo_hit,
            reproducible=finding.reproducible,
            not_fully_optimised=finding.not_fully_optimised,
            run_time_ms=round((self.clock.monotonic() - project.work_started_s) * _MILLISECONDS_PER_SECOND),
            memo_source_run_id=None if project.memo_source is None else project.memo_source.plan_run_id,
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

    def __init__(self, clock: Clock, progress: PlanJobProgress, work_started_s: float) -> None:
        self._clock = clock
        self._progress = progress
        self._work_started_s = work_started_s
        self.count = 0

    def found(self, incumbent: Incumbent) -> None:
        self.count += 1
        shown = {
            "unconfirmed_legs": incumbent.unconfirmed_legs,
            "retraces": incumbent.retraces,
            "objective": incumbent.objective,
            "found_at_s": self._clock.monotonic() - self._work_started_s,
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


def _ended(progress: PlanJobProgress, stored: StoredRun) -> StoredRun:
    progress.note(reproducible=stored.reproducible, not_fully_optimised_reason=stored.not_fully_optimised)
    if stored.reason is not None:
        progress.note(reason=stored.reason)
    return stored


def _added(first: LegsFound, second: LegsFound) -> LegsFound:
    return LegsFound(first.new + second.new, first.cached + second.cached, first.total + second.total)


def _note_legs(progress: PlanJobProgress, found: LegsFound) -> None:
    progress.note(legs_new=found.new, legs_cached=found.cached)


def _evidence_of(content: bytes, retraced: bool) -> CanonicalFileEvidence:
    sha256 = canonical_file_sha256(content)
    try:
        points = parse_canonical_points_file(content)
    except InvalidCanonicalPointsFileError:
        points = ()
    if not points:
        return CanonicalFileEvidence(sha256, 0, None, None)
    reversed_sha256 = reversed_points_sha256(points) if retraced else None
    return CanonicalFileEvidence(sha256, len(points), points[0].coordinate, points[-1].coordinate, reversed_sha256)


def _retrace_hashes(files: dict[str, CanonicalFileEvidence], retraced: set[str]) -> dict[str, str]:
    """The reversed points' hash of each retraced track whose file could be read as points."""
    found = {track_id: files[track_id].reversed_sha256 for track_id in retraced if track_id in files}
    return {track_id: sha256 for track_id, sha256 in found.items() if sha256 is not None}
