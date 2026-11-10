"""DiagnosticsService (DV-3, kpi-contracts K2, K3, K5, K7 and `diagnostics_endpoint`): behind `GET /api/diagnostics`.

Reads through the read-only `DiagnosticsReader` port and does the arithmetic here, so it is tested without SQL:
- the window is the last `days` days (default 30) of job starts; `project_id` limits every figure to that project.
- K5: every p95 is the nearest-rank p95 (with fewer than 20 values that is their max) over the cold jobs it covers:
  done, failed and cancelled alike, failed and cancelled with `elapsed_ms` as a lower bound (D177); memo hits are not
  cold plans and are only counted (`memo_hit_jobs`). Retried and second-pass > 700 jobs are counted and stay in every
  p95. Bands by `items_included`: le_30, 31_59, 60, 61_70. Until `plan.run.geometry_served` exists (slice 06a) e2e is
  `elapsed_ms` for every job, and `e2e_source` says so.
- K7: done jobs per (project, local day in Europe/Rome), median and max, projects named '__...' left out.
- K2: Failed runs with `internal_invariant_violation`; K3: runs whose stops miss an item of `inputs.included_item_ids`
  (until the consideration report exists, slice 04); a Failed run omits none. Both all time and over the window.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from overland_planner.application.ports.clock import Clock
from overland_planner.application.ports.diagnostics_reader import DiagnosticsReader, JobLogRow, PlanRunRow

DEFAULT_DAYS = 30
DAY_ZONE = ZoneInfo("Europe/Rome")  # kpi-contracts timezone_for_day_buckets
EXCLUDED_PREFIX = "__"  # kpi-contracts exclusions: fixtures loaded by hand
HEADLINE_BAND = "60"
SECOND_PASS_HEAVY = 700
INVARIANT_VIOLATION = "internal_invariant_violation"
_MILLISECONDS_PER_SECOND = 1000
BANDS: Mapping[str, range] = {"le_30": range(31), "31_59": range(31, 60), "60": range(60, 61), "61_70": range(61, 71)}


class UnknownProjectError(Exception):
    """The diagnostics were asked for a project that does not exist."""


@dataclass(frozen=True)
class K2:
    invariant_violations: Mapping[str, int]


@dataclass(frozen=True)
class K3:
    report_omissions: Mapping[str, int]


@dataclass(frozen=True)
class K5:
    stage_p95_s: Mapping[str, float | None]  # only the stages some cold job recorded, so never None
    solve_p95_s: Mapping[str, float | None]
    e2e_p95_s: float | None
    e2e_p95_by_band_s: Mapping[str, float | None]
    e2e_source: str
    retried_jobs: Mapping[str, int]
    second_pass_gt_700_jobs: Mapping[str, int]
    failed_jobs: Mapping[str, int]
    cancelled_jobs: Mapping[str, int]
    memo_hit_jobs: Mapping[str, int]


@dataclass(frozen=True)
class RunsPerProjectDay:
    median: float | None
    max: int | None


@dataclass(frozen=True)
class K7:
    runs_per_project_day: RunsPerProjectDay


@dataclass(frozen=True)
class DiagnosticsReport:
    version: str
    process_started_at: datetime
    days: int
    k2: K2
    k3: K3
    k5: K5
    k7: K7
    jobs_by_terminal_state: Mapping[str, int]
    retried_jobs: int
    second_pass_jobs: int


def nearest_rank_p95(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    rank = (95 * len(ordered) + 99) // 100  # ceil(0.95 n) in integers
    return ordered[rank - 1]


def _band(job: JobLogRow) -> str | None:
    return next((name for name, sizes in BANDS.items() if job.items_included in sizes), None)


def _stage_seconds(jobs: Iterable[JobLogRow], stage: str) -> list[float]:
    return [
        job.stage_ms[stage] / _MILLISECONDS_PER_SECOND
        for job in jobs
        if job.stage_ms is not None and stage in job.stage_ms
    ]


class _JobFigures:
    """K5 and the job totals over the window's job rows."""

    def __init__(self, jobs: Sequence[JobLogRow]) -> None:
        self._jobs = jobs
        self._banded = {name: [job for job in jobs if _band(job) == name] for name in BANDS}

    def k5(self) -> K5:
        cold = [job for job in self._jobs if not job.memo_hit]
        stages = sorted({stage for job in cold for stage in job.stage_ms or {}})
        e2e = self._per_band(lambda rows: nearest_rank_p95(job.elapsed_ms / _MILLISECONDS_PER_SECOND for job in rows))
        return K5(
            stage_p95_s={stage: nearest_rank_p95(_stage_seconds(cold, stage)) for stage in stages},
            solve_p95_s=self._per_band(lambda rows: nearest_rank_p95(_stage_seconds(rows, "solve"))),
            e2e_p95_s=e2e[HEADLINE_BAND],
            e2e_p95_by_band_s=e2e,
            e2e_source="elapsed_ms",
            retried_jobs=self._count_per_band(lambda job: job.retried is True),
            second_pass_gt_700_jobs=self._count_per_band(lambda job: (job.second_pass_pairs or 0) > SECOND_PASS_HEAVY),
            failed_jobs=self._count_per_band(lambda job: job.terminal_state == "failed"),
            cancelled_jobs=self._count_per_band(lambda job: job.terminal_state == "cancelled"),
            memo_hit_jobs=self._count_per_band(lambda job: job.memo_hit),
        )

    def by_terminal_state(self) -> dict[str, int]:
        return dict(Counter(job.terminal_state for job in self._jobs))

    def count(self, keep: Callable[[JobLogRow], bool]) -> int:
        return sum(1 for job in self._jobs if keep(job))

    def _per_band[T](self, figure: Callable[[list[JobLogRow]], T]) -> dict[str, T]:
        return {name: figure([job for job in rows if not job.memo_hit]) for name, rows in self._banded.items()}

    def _count_per_band(self, keep: Callable[[JobLogRow], bool]) -> dict[str, int]:
        return {name: sum(1 for job in rows if keep(job)) for name, rows in self._banded.items()}


def _variants(jobs: Iterable[JobLogRow]) -> K7:
    per_day = Counter(
        (job.project_id, job.started_at.astimezone(DAY_ZONE).date())
        for job in jobs
        if job.terminal_state == "done" and not (job.project_name or "").startswith(EXCLUDED_PREFIX)
    )
    counts = list(per_day.values())
    if not counts:
        return K7(RunsPerProjectDay(median=None, max=None))
    return K7(RunsPerProjectDay(median=statistics.median(counts), max=max(counts)))


def _broke_a_hard_rule(run: PlanRunRow) -> bool:
    return run.status == "failed" and run.failure_reason == INVARIANT_VIOLATION


def _left_an_item_out(run: PlanRunRow) -> bool:
    return run.status != "failed" and not set(run.included_item_ids) <= set(run.stop_item_ids)


class DiagnosticsService:
    def __init__(self, reader: DiagnosticsReader, clock: Clock, *, version: str, process_started_at: datetime) -> None:
        self._reader = reader
        self._clock = clock
        self._version = version
        self._process_started_at = process_started_at

    def report(self, *, days: int = DEFAULT_DAYS, project_id: str | None = None) -> DiagnosticsReport:
        """Raises `UnknownProjectError` when `project_id` names no project. Reading changes nothing."""
        if project_id is not None and not self._reader.project_exists(project_id):
            raise UnknownProjectError(project_id)
        since = self._clock.now() - timedelta(days=days)
        jobs = [job for job in self._reader.jobs_since(since) if project_id in (None, job.project_id)]
        runs = [run for run in self._reader.plan_runs() if project_id in (None, run.project_id)]
        figures = _JobFigures(jobs)
        return DiagnosticsReport(
            version=self._version,
            process_started_at=self._process_started_at,
            days=days,
            k2=K2(self._run_check(runs, since, _broke_a_hard_rule)),
            k3=K3(self._run_check(runs, since, _left_an_item_out)),
            k5=figures.k5(),
            k7=_variants(jobs),
            jobs_by_terminal_state=figures.by_terminal_state(),
            retried_jobs=figures.count(lambda job: job.retried is True),
            second_pass_jobs=figures.count(lambda job: (job.second_pass_pairs or 0) > 0),
        )

    @staticmethod
    def _run_check(runs: Sequence[PlanRunRow], since: datetime, failed: Callable[[PlanRunRow], bool]) -> dict[str, int]:
        return {
            "all_time": sum(1 for run in runs if failed(run)),
            "window": sum(1 for run in runs if failed(run) and run.created_at >= since),
        }
