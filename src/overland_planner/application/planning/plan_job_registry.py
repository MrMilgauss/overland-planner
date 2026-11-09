"""Plan job registry (ADR-015): plan jobs in memory, each on its own daemon thread, so a running job never blocks exit.

A job moves `queued -> computing_legs -> solving -> finalising` and ends in exactly one terminal state, published in one
assignment together with its `plan_run_id`: a poll never sees a run before the job is done. Solver-side outcomes end
`done` with a Failed run (D122). `failed` is anything else the work raises, SystemExit too, since a job without an
ending would hold its project in 409 until a restart: no run, reason null (ADR-015 fixes the codes and none covers it)
and a fixed message. It is logged and the thread then ends. `refused`, `cancelled` and `timed_out` arrive with Stop and
the limits.

A project has one active job: `start` checks and registers under one lock. One solver child runs at a time (D133): a job
that reaches the solve stage while the slot is busy shows `waiting_for_optimizer`, holding neither a lock of this
registry nor the writer lock, and every ending of a solve frees the slot. "Max 2 jobs overall" is not enforced: ADR-015
names no answer for a third project, so its job is accepted and waits for the slot like the second.

Finished jobs are kept for 10 minutes by the `Clock` port and forgotten on the next `start` or `get`; nothing waits on
the clock. Each job logs one `plan.job.finished` line before its end is published, with the kpi-contracts field names;
fields owned by later slices are null. A failed job names only the exception's class (D197). A job carries the
`ignore_memo` it was started with to its work, its poll and its log line; `memo_hit` is what its work noted, false until
the memo gives the order.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Literal, Protocol

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.event_log import EventLog

PlanJobState = Literal["queued", "computing_legs", "waiting_for_optimizer", "solving", "finalising", "done", "failed"]

KEEP_FINISHED_S = 600.0
FAILED_MESSAGE = "The plan could not be calculated - nothing was changed"
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


@dataclass(frozen=True)
class StoredRun:
    """The run a finished plan stored. `reason` is the failure reason of a Failed run."""

    plan_run_id: str
    reason: str | None


class PlanJobProgress(Protocol):
    def enter(self, state: PlanJobState) -> None: ...

    def note(self, **facts: object) -> None:
        """Facts for the job's `plan.job.finished` line."""
        ...

    def solver_slot(self) -> AbstractContextManager[None]:
        """Holds the one solver slot while in `solving`, waiting for it first if another job has it."""
        ...


class PlanWork(Protocol):
    def run(self, project_id: str, progress: PlanJobProgress, *, ignore_memo: bool = False) -> StoredRun: ...


@dataclass(frozen=True)
class _Ending:
    state: PlanJobState
    reason: str | None
    message: str | None
    plan_run_id: str | None
    ended_s: float


class _Job:
    def __init__(
        self, job_id: str, project_id: str, started_s: float, slot: threading.Lock, *, ignore_memo: bool
    ) -> None:
        self.id = job_id
        self.project_id = project_id
        self.started_s = started_s
        self.ignore_memo = ignore_memo
        self._slot = slot
        self.facts: dict[str, object] = {"ignore_memo": ignore_memo, "memo_hit": False}
        self.ending: _Ending | None = None
        self._state: PlanJobState = "queued"

    def enter(self, state: PlanJobState) -> None:
        self._state = state

    def note(self, **facts: object) -> None:
        self.facts.update(facts)

    @contextmanager
    def solver_slot(self) -> Iterator[None]:
        if not self._slot.acquire(blocking=False):
            self.enter("waiting_for_optimizer")
            self._slot.acquire()
        try:
            self.enter("solving")
            yield
        finally:
            self._slot.release()

    def is_active(self) -> bool:
        return self.ending is None

    def is_expired(self, now_s: float) -> bool:
        ending = self.ending
        return ending is not None and now_s - ending.ended_s >= KEEP_FINISHED_S

    def view(self, now_s: float) -> PlanJobView:
        shown = self.ending or self._so_far(now_s)
        return PlanJobView(
            self.id,
            self.project_id,
            shown.state,
            shown.reason,
            shown.message,
            shown.plan_run_id,
            elapsed_s=shown.ended_s - self.started_s,
            ignore_memo=self.ignore_memo,
            memo_hit=self.memo_hit(),
        )

    def _so_far(self, now_s: float) -> _Ending:
        """A running job as a poll at `now_s` shows it: its state, nothing more yet."""
        return _Ending(self._state, reason=None, message=None, plan_run_id=None, ended_s=now_s)

    def memo_hit(self) -> bool:
        return self.facts.get("memo_hit") is True


class PlanJobRegistry:
    def __init__(self, clock: Clock, work: PlanWork, event_log: EventLog) -> None:
        self._clock = clock
        self._work = work
        self._event_log = event_log
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()
        self._solver_slot = threading.Lock()

    def has_active_job(self, project_id: str) -> bool:
        with self._lock:
            return self._active_in(project_id)

    def start(self, project_id: str, *, ignore_memo: bool = False) -> str | None:
        """Start the job on its own thread and answer at once with its id; `None` if the project has an active job."""
        job = _Job(uuid.uuid4().hex, project_id, self._clock.monotonic(), self._solver_slot, ignore_memo=ignore_memo)
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

    def _active_in(self, project_id: str) -> bool:
        return any(job.project_id == project_id and job.is_active() for job in self._jobs.values())

    def _forget_expired(self) -> None:
        now_s = self._clock.monotonic()
        for job in [job for job in self._jobs.values() if job.is_expired(now_s)]:
            del self._jobs[job.id]

    def _run(self, job: _Job) -> None:
        ending = self._ending_of(job)
        try:
            self._log_finished(job, ending)
        finally:
            job.ending = ending

    def _ending_of(self, job: _Job) -> _Ending:
        try:
            stored = self._work.run(job.project_id, job, ignore_memo=job.ignore_memo)
        except BaseException as error:
            job.note(error_class=type(error).__name__)
            return _Ending("failed", None, FAILED_MESSAGE, None, self._clock.monotonic())
        return _Ending("done", stored.reason, None, stored.plan_run_id, self._clock.monotonic())

    def _log_finished(self, job: _Job, ending: _Ending) -> None:
        log = self._event_log.warning if ending.state == "failed" else self._event_log.info
        fields = {**dict.fromkeys(_NULL_UNTIL_NOTED), **job.facts}
        log(
            "plan.job.finished",
            **fields,
            job_id=job.id,
            project_id=job.project_id,
            terminal_state=ending.state,
            plan_run_id=ending.plan_run_id,
            elapsed_ms=round((ending.ended_s - job.started_s) * _MILLISECONDS_PER_SECOND),
        )
