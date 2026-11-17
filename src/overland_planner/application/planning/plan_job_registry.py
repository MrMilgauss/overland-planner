"""Plan job registry (ADR-015): plan jobs in memory, each on its own daemon thread, so a running job never blocks exit.

A job moves `queued -> computing_legs -> solving -> finalising` and ends in exactly one terminal state, published in one
assignment together with its `plan_run_id`: a poll never sees a run before the job is done. Solver-side outcomes end
`done` with a Failed run (D122), whose message, if it has words, names the run (D151). `failed` is anything else the
work raises, SystemExit too, since a job without an ending would hold its project in 409 until a restart: no run,
reason null (ADR-015 fixes the codes and none covers it) and a fixed message. It is logged and the thread then ends.
`refused` arrives with the look-up-side limit.

A project has one active job: `start` checks and registers under one lock. One solver child runs at a time (D133): a job
that reaches the solve stage while the slot is busy shows `waiting_for_optimizer`, holding neither a lock of this
registry nor the writer lock, and every ending of a solve frees the slot. "Max 2 jobs overall" is not enforced: ADR-015
names no answer for a third project, so its job is accepted and waits for the slot like the second. The wait gives up
on Stop (`cancelled`) and at the work's feasibility limit counted from the job's start (`timed_out`); neither stores a
run, and both end with words and a reason (`stopped`, `timeout`).

Stop (US-06b, ADR-015 state table, D136) is idempotent and answers the current poll: `stop` is `None` only for an
unknown or expired job. The poll shows `stoppable` true in every state before `finalising` and false from then on; a
Stop when it is false changes nothing, so the run being written completes. While solving a Stop sets the stop signal
the job's solver slot hands the solve (brief section 6), and the solve ends with the best so far. A job that a Stop
ended logs one `plan.job.stopped` line (brief section 12) before its `plan.job.finished` line, with the state it was
stopped in.

The work runs on a thread of its own, which the job's thread watches (06-09, ADR-015 'any state before solving'): in
`queued` and `computing_legs` a Stop ends the job `cancelled` at once and the feasibility limit from the job's start
ends it `timed_out` with the look-up words (D151, D157), even while the work is inside a road-map call. Neither stores
a run. The abandoned work notices at its next step (its next state or fact raises the ending), so it stores nothing,
and it holds no writer lock while it waits; the legs it was answered stay with the leg resolver. The watch looks at the
`Clock` port every quarter of a second; a Stop wakes it at once.

Finished jobs are kept for 10 minutes by the `Clock` port and forgotten on the next `start` or `get`; nothing waits on
the clock. Each job logs one `plan.job.finished` line before its end is published, with the kpi-contracts field names;
fields owned by later slices, and those a job ended before it could note, are null; `unconfirmed_legs` and
`retraces` are the stored plan's, read from the model's real tables (07-08). A failed job names only the exception's
class (D197). With a `PlanJobLog`, the
line's values are then written as the job's one `plan_job_log` row (ADR-015 DV-2), after the run is stored and before
the end is published; a row that cannot be written changes nothing of the ending and logs `plan.job.log_failed` at
warning with the error's class. The row adds `solver_wait_s`, which the line leaves out (kpi-contracts): the seconds by
the `Clock` port from the job asking for the solver slot to taking it, or to its wait giving up on Stop or at the
feasibility limit; 0.0 when the slot was free; null for a job that ended before it asked (before the solve stage).
The poll shows `stage_ms`, `legs_total`, `legs_new`, `legs_cached` (the road legs asked of the road map and those
known without asking, as they arrive) and `items_included` once the work noted them, and `incumbent` (null until the
first valid route): the last incumbent the solve streamed, which the line leaves out (it counts them in `incumbents`),
and `notices` (the large-project notice, D146), which the line leaves out too.
A job carries the `ignore_memo` it was started with to its work, its poll and its log line; `memo_hit` is what its work
noted, false until the memo gives the order.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog
from overland_planner.application.ports.plan_job_log import PlanJobLog, PlanJobLogEntry
from overland_planner.application.ports.routing_provider import (
    ProviderUnavailable,
    ProviderUnreachable,
    RoutingProviderError,
)
from overland_planner.application.ports.tour_solver import SolveLimits, StopSignal
from overland_planner.domain.planning.run_messages import (
    ENGINE_NOT_READY_MESSAGE,
    ENGINE_NOT_READY_REASON,
    ENGINE_UNREACHABLE_MESSAGE,
    ENGINE_UNREACHABLE_REASON,
    NotFullyOptimised,
)

PlanJobState = Literal[
    "queued",
    "computing_legs",
    "waiting_for_optimizer",
    "solving",
    "finalising",
    "done",
    "failed",
    "cancelled",
    "timed_out",
]

KEEP_FINISHED_S = 600.0
FAILED_MESSAGE = "The plan could not be calculated - nothing was changed"
CANCELLED_MESSAGE = "Stopped - nothing was changed"
WAIT_TIMED_OUT_MESSAGE = "No valid route found within the time limit - nothing was changed"
STOPPED_REASON = "stopped"
_SLOT_WAIT_STEP_S = 0.25  # the longest wait for the solver slot before Stop and the feasibility limit are checked
_WATCH_STEP_S = 0.25  # the longest wait of the job's thread before it looks at the feasibility limit again
_BEFORE_SOLVING = frozenset({"queued", "computing_legs", "waiting_for_optimizer"})
_ENDED_BY_THE_WATCH = frozenset({"queued", "computing_legs"})  # the solver slot's wait gives up by itself
_NOT_STOPPABLE = frozenset({"finalising", "done", "failed", "cancelled", "timed_out"})
_MILLISECONDS_PER_SECOND = 1000
_NULL_UNTIL_NOTED = (
    "items_included",
    "legs_total",
    "legs_new",
    "legs_cached",
    "points_located",
    "points_new",
    "second_pass_pairs",
    "retried",
    "stage_ms",
    "solver_solutions",
    "incumbents",
    "reproducible",
    "not_fully_optimised_reason",
    "unconfirmed_legs",
    "retraces",
    "provider_id",
)
_POLL_ONLY = ("incumbent", "notices")
_ENGINE_ENDINGS: dict[type[RoutingProviderError], tuple[str, str]] = {  # D248: the engine's reason and words
    ProviderUnreachable: (ENGINE_UNREACHABLE_REASON, ENGINE_UNREACHABLE_MESSAGE),
    ProviderUnavailable: (ENGINE_NOT_READY_REASON, ENGINE_NOT_READY_MESSAGE),
}


@dataclass(frozen=True)
class PlanJobView:
    """What a poll shows of a job. `plan_run_id` is null until the run is stored."""

    id: str
    project_id: str
    state: PlanJobState
    reason: str | None
    message: str | None
    plan_run_id: str | None
    elapsed_s: float
    ignore_memo: bool = False
    memo_hit: bool = False
    stage_ms: dict[str, int] | None = None
    legs_total: int | None = None
    legs_new: int | None = None
    legs_cached: int | None = None
    items_included: int | None = None
    second_pass_pairs: int | None = None
    retried: bool | None = None
    incumbent: dict[str, float] | None = None
    stoppable: bool = True
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredRun:
    """The run a finished plan stored. `reason` is the failure reason of a Failed run; `reproducible` and
    `not_fully_optimised` are the run's flags (brief section 8); `message` is what the ended job says of it (D151)."""

    plan_run_id: str
    reason: str | None
    reproducible: bool = True
    not_fully_optimised: NotFullyOptimised | None = None
    message: str | None = None


class PlanJobProgress(Protocol):
    def enter(self, state: PlanJobState) -> None: ...

    def note(self, **facts: object) -> None:
        """Facts for the job's `plan.job.finished` line."""
        ...

    def solver_slot(self) -> AbstractContextManager[StopSignal | None]:
        """Holds the one solver slot while in `solving`, waiting for it first if another job has it; answers the stop
        signal of the solve it holds (`None`: none)."""
        ...


class PlanWork(Protocol):
    @property
    def limits(self) -> SolveLimits:
        """The limits of the work. The work counts its deadlines from its own start; the registry counts the
        feasibility one from the job's start (under 1 ms earlier), where its watch and a wait for the slot give up."""
        ...

    def run(self, project_id: str, progress: PlanJobProgress, *, ignore_memo: bool = False) -> StoredRun: ...


class _EndedBeforeSolving(Exception):
    """A job that ended before its solve: no run, its terminal state, reason and words."""

    def __init__(self, state: PlanJobState, reason: str, message: str) -> None:
        super().__init__(state)
        self.state, self.reason, self.message = state, reason, message


def _cancelled() -> _EndedBeforeSolving:
    return _EndedBeforeSolving("cancelled", STOPPED_REASON, CANCELLED_MESSAGE)


def _timed_out() -> _EndedBeforeSolving:
    return _EndedBeforeSolving("timed_out", "timeout", WAIT_TIMED_OUT_MESSAGE)


class _SolverSlot:
    """The one solver slot (D133). A wait for it gives up on Stop and at the job's feasibility give-up instant."""

    def __init__(self, clock: Clock) -> None:
        self._lock = threading.Lock()
        self._clock = clock

    def take(
        self, give_up_at_s: float, stop: threading.Event, waiting: Callable[[], None], waited: Callable[[float], None]
    ) -> None:
        """Takes the slot, calling `waiting` first when it is busy; raises the ending when the wait gives up. `waited`
        is told the seconds of the wait by the `Clock` port as it ends either way: 0.0 when the slot was free."""
        if self._lock.acquire(blocking=False):
            waited(0.0)
            return
        asked_s = self._clock.monotonic()
        try:
            waiting()
            while not self._lock.acquire(timeout=_SLOT_WAIT_STEP_S):
                if stop.is_set():
                    raise _cancelled()
                if self._clock.monotonic() >= give_up_at_s:
                    raise _timed_out()
        finally:
            waited(self._clock.monotonic() - asked_s)

    def release(self) -> None:
        self._lock.release()


class _WorkThread:
    """The job's work on a daemon thread of its own; its end wakes the job's thread."""

    def __init__(self, run: Callable[[], StoredRun], job: _Job) -> None:
        self._run = run
        self._job = job
        self._done = threading.Event()
        self._stored: StoredRun | None = None
        self._raised: BaseException | None = None
        threading.Thread(target=self._work, name=f"plan-work-{job.id}", daemon=True).start()

    def _work(self) -> None:
        try:
            self._stored = self._run()
        except BaseException as error:  # handed to the job's thread, which ends the job with it
            self._raised = error
        finally:
            self._done.set()
            self._job.wake.set()

    def finished(self) -> bool:
        return self._done.is_set()

    def outcome(self) -> StoredRun:
        """What the work stored; raises what it raised."""
        if self._raised is not None:
            raise self._raised
        if self._stored is None:
            raise RuntimeError("the work ended without storing or raising")
        return self._stored


@dataclass(frozen=True)
class _Ending:
    state: PlanJobState
    reason: str | None
    message: str | None
    plan_run_id: str | None
    ended_s: float
    ended_at: datetime | None = None


class _Job:
    def __init__(
        self,
        job_id: str,
        project_id: str,
        started: tuple[float, datetime],
        slot: _SolverSlot,
        *,
        ignore_memo: bool,
        feasibility_s: float,
    ) -> None:
        self.id = job_id
        self.project_id = project_id
        self.started_s, self.started_at = started
        self.give_up_at_s = self.started_s + feasibility_s  # the feasibility limit from the job's start
        self.ignore_memo = ignore_memo
        self._slot = slot
        self.facts: dict[str, object] = {"ignore_memo": ignore_memo, "memo_hit": False}
        self.ending: _Ending | None = None
        self.stopped_in: PlanJobState | None = None
        self.solver_wait_s: float | None = None  # the row's own field (ADR-015): null until the job asks for the slot
        self._state: PlanJobState = "queued"
        self._stop = threading.Event()
        self.wake = threading.Event()  # set by a Stop and by the end of the work, for the job's thread
        self._abandoned: _EndedBeforeSolving | None = None  # the ending the watch gave the job while the work ran
        self._guard = threading.Lock()  # a Stop, a change of state, a fact and the watch never interleave

    def enter(self, state: PlanJobState) -> None:
        """Raises the `cancelled` ending instead when a Stop came before the solve; an abandoned job, its ending."""
        with self._guard:
            if self._abandoned is not None:
                raise self._abandoned
            if self._stop.is_set() and self._state in _BEFORE_SOLVING:
                raise _cancelled()
            self._state = state

    def note(self, **facts: object) -> None:
        """Raises the ending of an abandoned job: its line is written, so nothing more is noted."""
        with self._guard:
            if self._abandoned is not None:
                raise self._abandoned
            self.facts.update(facts)

    def request_stop(self) -> None:
        with self._guard:
            if self.ending is not None or self._state in _NOT_STOPPABLE or self._stop.is_set():
                return
            self.stopped_in = self._state
            self._stop.set()
        self.wake.set()

    def abandon_before_solving(self, now_s: float) -> _EndedBeforeSolving | None:
        """The ending of a job still before its road legs are found when a Stop came or the feasibility limit is
        reached, `None` otherwise; from then on the work's next state or fact raises it."""
        with self._guard:
            if self._abandoned is not None or self._state not in _ENDED_BY_THE_WATCH:
                return None
            if self._stop.is_set():
                self._abandoned = _cancelled()
            elif now_s >= self.give_up_at_s:
                self._abandoned = _timed_out()
            return self._abandoned

    def ended_for(self, reason: str) -> None:
        """The reason of an ending before the solve, noted even on an abandoned job, which takes no more facts."""
        with self._guard:
            self.facts["reason"] = reason

    def fact_values(self) -> dict[str, object]:
        with self._guard:
            return dict(self.facts)

    def was_stopped(self, ending: _Ending) -> bool:
        return self.stopped_in is not None and STOPPED_REASON in (
            ending.reason,
            self.facts.get("not_fully_optimised_reason"),
        )

    @contextmanager
    def solver_slot(self) -> Iterator[StopSignal]:
        self._slot.take(self.give_up_at_s, self._stop, lambda: self.enter("waiting_for_optimizer"), self._waited)
        try:
            self.enter("solving")
            yield self._stop
        finally:
            self._slot.release()

    def _waited(self, seconds: float) -> None:
        self.solver_wait_s = seconds

    def is_active(self) -> bool:
        return self.ending is None

    def is_expired(self, now_s: float) -> bool:
        ending = self.ending
        return ending is not None and now_s - ending.ended_s >= KEEP_FINISHED_S

    def view(self, now_s: float) -> PlanJobView:
        shown = self.ending or self._so_far(now_s)
        facts = self.fact_values()  # one copy under the guard per poll
        return PlanJobView(
            self.id,
            self.project_id,
            shown.state,
            shown.reason,
            shown.message,
            shown.plan_run_id,
            elapsed_s=shown.ended_s - self.started_s,
            ignore_memo=self.ignore_memo,
            memo_hit=facts.get("memo_hit") is True,
            stage_ms=_fact(facts, "stage_ms", dict),
            legs_total=_fact(facts, "legs_total", int),
            legs_new=_fact(facts, "legs_new", int),
            legs_cached=_fact(facts, "legs_cached", int),
            items_included=_fact(facts, "items_included", int),
            second_pass_pairs=_fact(facts, "second_pass_pairs", int),
            retried=_fact(facts, "retried", bool),
            incumbent=_fact(facts, "incumbent", dict),
            stoppable=shown.state not in _NOT_STOPPABLE,
            notices=_fact(facts, "notices", tuple) or (),
        )

    def _so_far(self, now_s: float) -> _Ending:
        """A running job as a poll at `now_s` shows it: its state, nothing more yet."""
        return _Ending(self._state, reason=None, message=None, plan_run_id=None, ended_s=now_s)


def _fact[T](facts: dict[str, object], name: str, kind: type[T]) -> T | None:
    value = facts.get(name)
    return value if isinstance(value, kind) else None


class PlanJobRegistry:
    def __init__(self, clock: Clock, work: PlanWork, event_log: EventLog, *, job_log: PlanJobLog | None = None) -> None:
        self._job_log = job_log
        self._clock = clock
        self._work = work
        self._event_log = event_log
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()
        self._solver_slot = _SolverSlot(clock)

    def has_active_job(self, project_id: str) -> bool:
        with self._lock:
            return self._active_in(project_id)

    def start(self, project_id: str, *, ignore_memo: bool = False) -> str | None:
        """Start the job on its own thread and answer at once with its id; `None` if the project has an active job."""
        started = (self._clock.monotonic(), self._clock.now())
        feasibility_s = self._work.limits.feasibility_s
        job = _Job(
            uuid.uuid4().hex,
            project_id,
            started,
            self._solver_slot,
            ignore_memo=ignore_memo,
            feasibility_s=feasibility_s,
        )
        with self._lock:
            if self._active_in(project_id):
                return None
            self._forget_expired()
            threading.Thread(target=self._run, args=(job,), name=f"plan-job-{job.id}", daemon=True).start()
            self._jobs[job.id] = job
        return job.id

    def get(self, job_id: str) -> PlanJobView | None:
        """The job as a poll shows it, or `None` when it is unknown or expired."""
        with self._lock:
            self._forget_expired()
            job = self._jobs.get(job_id)
        return None if job is None else job.view(self._clock.monotonic())

    def stop(self, job_id: str) -> PlanJobView | None:
        """Stop and use best so far (D136): the job as a poll shows it right after, `None` when unknown or expired."""
        with self._lock:
            self._forget_expired()
            job = self._jobs.get(job_id)
        if job is None:
            return None
        job.request_stop()
        return job.view(self._clock.monotonic())

    def _active_in(self, project_id: str) -> bool:
        return any(job.project_id == project_id and job.is_active() for job in self._jobs.values())

    def _forget_expired(self) -> None:
        now_s = self._clock.monotonic()
        for job in [job for job in self._jobs.values() if job.is_expired(now_s)]:
            del self._jobs[job.id]

    def _run(self, job: _Job) -> None:
        ending = self._ending_of(job)
        try:
            if job.was_stopped(ending):
                self._event_log.info(
                    "plan.job.stopped",
                    job_id=job.id,
                    project_id=job.project_id,
                    state=job.stopped_in,
                    terminal_state=ending.state,
                    plan_run_id=ending.plan_run_id,
                )
            fields = self._finished_fields(job, ending)
            log = self._event_log.warning if ending.state == "failed" else self._event_log.info
            log("plan.job.finished", **fields)
            self._write_row(job, ending, fields)
        finally:
            job.ending = ending

    def _ending_of(self, job: _Job) -> _Ending:
        work = _WorkThread(lambda: self._work.run(job.project_id, job, ignore_memo=job.ignore_memo), job)
        while not work.finished():
            abandoned = job.abandon_before_solving(self._clock.monotonic())
            if abandoned is not None:
                return self._ended_before_solving(job, abandoned)
            job.wake.wait(_WATCH_STEP_S)
            job.wake.clear()
        try:
            stored = work.outcome()
        except _EndedBeforeSolving as ended:
            return self._ended_before_solving(job, ended)
        except RoutingProviderError as error:
            return self._ended_by_the_engine(job, error)
        except BaseException as error:
            job.note(error_class=type(error).__name__)
            return self._ended_now("failed", None, FAILED_MESSAGE)
        return self._ended_now("done", stored.reason, stored.message, stored.plan_run_id)

    def _ended_by_the_engine(self, job: _Job, error: RoutingProviderError) -> _Ending:
        """The routing engine failed during the look-up (D248): `failed` with the engine's reason and words, no run; the
        legs answered stay with the leg resolver. A rejection has no words of its own: the failed job's."""
        reason, message = next(
            (ending for kind, ending in _ENGINE_ENDINGS.items() if isinstance(error, kind)), (None, FAILED_MESSAGE)
        )
        job.note(error_class=type(error).__name__)
        if reason is not None:
            job.ended_for(reason)
        self._event_log.warning(
            "routing.engine.error",
            job_id=job.id,
            project_id=job.project_id,
            error_class=type(error).__name__,
            reason=reason,
        )
        return self._ended_now("failed", reason, message)

    def _ended_before_solving(self, job: _Job, ended: _EndedBeforeSolving) -> _Ending:
        job.ended_for(ended.reason)
        return self._ended_now(ended.state, ended.reason, ended.message)

    def _ended_now(
        self, state: PlanJobState, reason: str | None, message: str | None, plan_run_id: str | None = None
    ) -> _Ending:
        """An ending at this moment of the `Clock` port: its monotonic time, then its date."""
        return _Ending(state, reason, message, plan_run_id, self._clock.monotonic(), self._clock.now())

    def _finished_fields(self, job: _Job, ending: _Ending) -> dict[str, object]:
        """The `plan.job.finished` fields, which the job's row holds too."""
        return {
            **dict.fromkeys(_NULL_UNTIL_NOTED),
            **{name: value for name, value in job.fact_values().items() if name not in _POLL_ONLY},
            "job_id": job.id,
            "project_id": job.project_id,
            "terminal_state": ending.state,
            "plan_run_id": ending.plan_run_id,
            "elapsed_ms": round((ending.ended_s - job.started_s) * _MILLISECONDS_PER_SECOND),
        }

    def _write_row(self, job: _Job, ending: _Ending, fields: dict[str, object]) -> None:
        if self._job_log is None:
            return
        row = {**fields, "solver_wait_s": job.solver_wait_s}
        entry = PlanJobLogEntry(job.started_at, ending.ended_at or job.started_at, row)
        try:
            self._job_log.append(entry)
        except Exception as error:  # a full disk must not change the ending, its run or its poll
            self._event_log.warning(
                "plan.job.log_failed", job_id=job.id, project_id=job.project_id, error_class=type(error).__name__
            )
