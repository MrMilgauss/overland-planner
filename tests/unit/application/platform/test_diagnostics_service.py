"""DiagnosticsService (DV-3, kpi-contracts K2, K3, K5, K7, `diagnostics_endpoint`): what `GET /api/diagnostics` reports.

Driving port: `DiagnosticsService(reader, clock, version=..., process_started_at=...).report(days=, project_id=)`;
the driven port `DiagnosticsReader` is an in-memory double holding the `plan_job_log`, `plan_runs` and `projects` rows,
which reading must leave unchanged. Oracles follow the definitions, not the production arithmetic: the nearest-rank p95
is the smallest value with at least 95 % of the values at or below it.
Test Budget: 7 behaviors (K5 figures, job totals, K7 variants, K2/K3 counts, G4 engine refusals, unknown project,
read-only) x 2 = 14; 8 property tests used.
Mutants judged equivalent (07-12, slice 01b precedent): `(job.second_pass_pairs or 0) -> or 1` in K5 (1 > 700 is as
false as 0 > 700); `(job.project_name or "") -> or "XXXX"` in K7 (neither starts with "__").
"""

from __future__ import annotations

import os
import statistics
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.platform.facade import DiagnosticsService, UnknownProjectError
from overland_planner.application.ports.diagnostics_reader import JobLogRow, PlanRunRow, RefusalRow
from overland_planner.application.ports.probe import ProbeResult
from tests.common.fakes import FakeClock
from tests.common.state_delta import assert_state_delta, set_to

NOW = datetime(2026, 11, 2, 19, 30, tzinfo=UTC)
STARTED = NOW - timedelta(hours=5)  # the process start, apart from the clock's now
VERSION = "0123456789ab"
ROME = ZoneInfo("Europe/Rome")
STAGES = ("snapshot", "matrix", "reach_model", "solve", "guard_persist")
BANDS = {"le_30": range(0, 31), "31_59": range(31, 60), "60": range(60, 61), "61_70": range(61, 71)}
PROJECTS = {"p1": "Alpi Occidentali", "p2": "Dolomiti 2028", "fx": "__perf fixture"}
STORED = {"plan_job_log", "plan_runs", "plan_refusals", "projects"}


class InMemoryDiagnosticsReader:
    """`DiagnosticsReader` double: the rows as stored; a window bound must be timezone-aware like the adapter's."""

    def __init__(
        self, jobs: Sequence[JobLogRow], runs: Sequence[PlanRunRow] = (), refusals: Sequence[RefusalRow] = ()
    ) -> None:
        self.jobs = list(jobs)
        self.runs = list(runs)
        self.refusals = list(refusals)
        self.projects = dict(PROJECTS)

    def project_exists(self, project_id: str) -> bool:
        assert project_id, "a project id is required"
        return project_id in self.projects

    def jobs_since(self, since: datetime) -> Sequence[JobLogRow]:
        assert since.tzinfo is not None, "the window bound must be timezone-aware"
        return [job for job in self.jobs if job.started_at >= since]

    def plan_runs(self) -> Sequence[PlanRunRow]:
        return list(self.runs)

    def refusals_since(self, since: datetime) -> Sequence[RefusalRow]:
        assert since.tzinfo is not None, "the window bound must be timezone-aware"
        return [refusal for refusal in self.refusals if refusal.created_at >= since]

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")

    def stored(self) -> dict[str, Any]:
        return {
            "plan_job_log": list(self.jobs),
            "plan_runs": list(self.runs),
            "plan_refusals": list(self.refusals),
            "projects": dict(self.projects),
        }


def service(reader: InMemoryDiagnosticsReader) -> DiagnosticsService:
    return DiagnosticsService(reader, FakeClock(NOW), version=VERSION, process_started_at=STARTED)


@contextmanager
def host_zone(zone: str) -> Iterator[None]:
    """The process's local time zone set to `zone` (the Pi's container runs in UTC), restored after."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = zone
    time.tzset()
    try:
        yield
    finally:
        if saved is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = saved
        time.tzset()


def p95(values: Sequence[float]) -> float | None:
    """Nearest-rank p95 by definition: the smallest value with at least 95 % of the values at or below it."""
    if not values:
        return None
    return min(v for v in values if 100 * sum(1 for w in values if w <= v) >= 95 * len(values))


def band_of(job: JobLogRow) -> str | None:
    return next((name for name, sizes in BANDS.items() if job.items_included in sizes), None)


# Up to 9 days back, so the default 30-day window and a short one both cut through the rows; a short window's bound
# itself is drawn too, a row started on it being inside the window.
ages = st.one_of(st.integers(min_value=0, max_value=9 * 24 * 60), st.sampled_from([24 * 60, 3 * 24 * 60]))
second_pass = st.one_of(st.none(), st.sampled_from([0, 700, 701]), st.integers(0, 1_000))  # > 700 is heavy
item_counts = st.one_of(st.none(), st.sampled_from([1, 30, 31, 59, 60, 61, 70, 71]), st.integers(1, 80))
stage_times = st.dictionaries(st.sampled_from(STAGES), st.integers(0, 120_000), max_size=len(STAGES))


@st.composite
def job_rows(draw: st.DrawFn) -> JobLogRow:
    project_id = draw(st.sampled_from([*PROJECTS, "gone"]))
    state = draw(st.sampled_from(["done", "failed", "cancelled"]))
    return JobLogRow(
        project_id=project_id,
        project_name=PROJECTS.get(project_id),
        started_at=NOW - timedelta(minutes=draw(ages)),
        terminal_state=state,
        elapsed_ms=draw(st.integers(0, 400_000)),
        memo_hit=state == "done" and draw(st.booleans()),
        items_included=draw(item_counts),
        stage_ms=draw(st.one_of(st.none(), stage_times)),
        retried=draw(st.sampled_from([None, False, True])),
        second_pass_pairs=draw(second_pass),
    )


job_logs = st.lists(job_rows(), max_size=45)
windows = st.sampled_from([1, 3, 30, 365])


def in_window(jobs: Sequence[JobLogRow], days: int) -> list[JobLogRow]:
    return [job for job in jobs if job.started_at >= NOW - timedelta(days=days)]


def seconds(milliseconds: Sequence[int]) -> list[float]:
    return [ms / 1000 for ms in milliseconds]


def expected_k5(jobs: Sequence[JobLogRow]) -> dict[str, Any]:
    cold = [job for job in jobs if not job.memo_hit]
    stages = {stage for job in cold for stage in (job.stage_ms or {})}
    banded = {name: [job for job in jobs if band_of(job) == name] for name in BANDS}
    cold_banded = {name: [job for job in rows if not job.memo_hit] for name, rows in banded.items()}

    def counted(keep: Any) -> dict[str, int]:
        return {name: sum(1 for job in rows if keep(job)) for name, rows in banded.items()}

    e2e = {name: p95(seconds([job.elapsed_ms for job in rows])) for name, rows in cold_banded.items()}
    return {
        "stage_p95_s": {s: p95(seconds([j.stage_ms[s] for j in cold if s in (j.stage_ms or {})])) for s in stages},
        "solve_p95_s": {
            name: p95(seconds([j.stage_ms["solve"] for j in rows if "solve" in (j.stage_ms or {})]))
            for name, rows in cold_banded.items()
        },
        "e2e_p95_s": e2e["60"],
        "e2e_p95_by_band_s": e2e,
        "e2e_source": "elapsed_ms",
        "retried_jobs": counted(lambda job: job.retried is True),
        "second_pass_gt_700_jobs": counted(lambda job: (job.second_pass_pairs or 0) > 700),
        "failed_jobs": counted(lambda job: job.terminal_state == "failed"),
        "cancelled_jobs": counted(lambda job: job.terminal_state == "cancelled"),
        "memo_hit_jobs": counted(lambda job: job.memo_hit),
    }


def k5_slot(report: Any) -> dict[str, Any]:
    k5 = report.k5
    return {name: getattr(k5, name) for name in expected_k5([])}


@given(jobs=job_logs, days=windows)
@settings(max_examples=150, deadline=None)
def test_every_reported_p95_is_the_nearest_rank_p95_of_exactly_the_cold_jobs_it_covers(
    jobs: list[JobLogRow], days: int
) -> None:
    reader = InMemoryDiagnosticsReader(jobs)
    before = {**reader.stored(), "k5": None}

    report = service(reader).report(days=days)

    after = {**reader.stored(), "k5": k5_slot(report)}
    universe = {*STORED, "k5"}
    assert_state_delta(before, after, universe, {"k5": set_to(expected_k5(in_window(jobs, days)))}, strict=True)


# Any number of jobs in one band, a multiple of 20 too (where 95 % of them is a whole number of jobs), all distinct.
band_sizes = st.one_of(st.sampled_from([20, 40, 60]), st.integers(1, 60))
band_times = band_sizes.flatmap(lambda n: st.lists(st.integers(0, 400_000), min_size=n, max_size=n, unique=True))


@given(values=band_times)
def test_a_band_reports_the_nearest_rank_p95_of_its_jobs_and_its_max_below_20_jobs(values: list[int]) -> None:
    jobs = [JobLogRow("p1", PROJECTS["p1"], NOW, "done", ms, False, items_included=60) for ms in values]

    report = service(InMemoryDiagnosticsReader(jobs)).report()

    expected = max(values) / 1000 if len(values) < 20 else p95(seconds(values))
    assert report.k5.e2e_p95_by_band_s["60"] == expected == report.k5.e2e_p95_s


@given(jobs=job_logs, days=windows)
@settings(max_examples=100, deadline=None)
def test_every_terminal_job_is_counted_and_retried_jobs_are_shown_apart(jobs: list[JobLogRow], days: int) -> None:
    reader = InMemoryDiagnosticsReader(jobs)
    universe = {*STORED, "jobs_by_terminal_state", "retried_jobs", "second_pass_jobs", "header"}
    before = {
        **reader.stored(),
        "jobs_by_terminal_state": None,
        "retried_jobs": None,
        "second_pass_jobs": None,
        "header": None,
    }

    report = service(reader).report(days=days)

    shown = in_window(jobs, days)
    after = {
        **reader.stored(),
        "jobs_by_terminal_state": dict(report.jobs_by_terminal_state),
        "retried_jobs": report.retried_jobs,
        "second_pass_jobs": report.second_pass_jobs,
        "header": (report.version, report.process_started_at, report.days),
    }
    expected = {
        "jobs_by_terminal_state": set_to(dict(Counter(job.terminal_state for job in shown))),
        "retried_jobs": set_to(sum(1 for job in shown if job.retried is True)),
        "second_pass_jobs": set_to(sum(1 for job in shown if (job.second_pass_pairs or 0) > 0)),
        "header": set_to((VERSION, STARTED, days)),  # the build and process the figures come from, and their window
    }
    assert_state_delta(before, after, universe, expected, strict=True)


@given(
    jobs=job_logs,
    days=windows,
    chosen=st.sampled_from([None, "p1", "p2"]),
)
@settings(max_examples=150, deadline=None)
def test_variants_are_the_median_and_max_of_done_jobs_per_project_and_local_day(
    jobs: list[JobLogRow], days: int, chosen: str | None
) -> None:
    reader = InMemoryDiagnosticsReader(jobs)
    before = {**reader.stored(), "k7": None}

    report = service(reader).report(days=days, project_id=chosen)

    per_day = Counter(
        (job.project_id, job.started_at.astimezone(ROME).date())
        for job in in_window(jobs, days)
        if job.terminal_state == "done"
        and not (job.project_name or "").startswith("__")
        and chosen in (None, job.project_id)
    )
    counts = list(per_day.values())
    oracle = {"median": statistics.median(counts) if counts else None, "max": max(counts, default=None)}
    k7 = report.k7.runs_per_project_day
    after = {**reader.stored(), "k7": {"median": k7.median, "max": k7.max}}
    assert_state_delta(before, after, {*STORED, "k7"}, {"k7": set_to(oracle)}, strict=True)


@given(
    evenings=st.sets(st.integers(min_value=1, max_value=8), min_size=1),
    zone=st.sampled_from(["UTC", "Pacific/Kiritimati", "America/Los_Angeles"]),
)
@settings(deadline=None)
def test_a_local_day_is_romes_whatever_zone_the_host_runs_in(evenings: set[int], zone: str) -> None:
    """Two done jobs an hour apart across Rome's midnight are two days in Rome and one day in the host's zone."""
    today = NOW.astimezone(ROME).date()
    late = [datetime.combine(today - timedelta(days=back), datetime.min.time(), ROME) for back in evenings]
    starts = [instant + offset for instant in late for offset in (timedelta(minutes=-30), timedelta(minutes=30))]
    jobs = [JobLogRow("p1", PROJECTS["p1"], start.astimezone(UTC), "done", 1_000, False) for start in starts]
    reader = InMemoryDiagnosticsReader(jobs)
    before = {**reader.stored(), "k7": None}

    with host_zone(zone):
        k7 = service(reader).report().k7.runs_per_project_day

    counts = list(Counter(start.astimezone(ROME).date() for start in starts).values())
    oracle = {"median": statistics.median(counts), "max": max(counts)}
    after = {**reader.stored(), "k7": {"median": k7.median, "max": k7.max}}
    assert_state_delta(before, after, {*STORED, "k7"}, {"k7": set_to(oracle)}, strict=True)


item_ids = st.lists(st.sampled_from(["a", "b", "c", "d"]), max_size=4, unique=True)


@st.composite
def plan_run_rows(draw: st.DrawFn) -> PlanRunRow:
    status = draw(st.sampled_from(["ready", "failed"]))
    included = tuple(draw(item_ids))
    # a retrace row repeats its track's item id (ADR-017 section 3): repeats must break neither count
    stops = () if status == "failed" else tuple(draw(st.lists(st.sampled_from(included or ("x",)))))
    reason = draw(st.sampled_from([None, "internal_invariant_violation", "infeasible"])) if status == "failed" else None
    return PlanRunRow(
        project_id=draw(st.sampled_from(list(PROJECTS))),
        created_at=NOW - timedelta(minutes=draw(ages)),
        status=status,
        failure_reason=reason,
        included_item_ids=included,
        stop_item_ids=stops,
    )


@given(runs=st.lists(plan_run_rows(), max_size=20), days=windows)
@settings(max_examples=100, deadline=None)
def test_broken_rules_and_report_omissions_are_counted_per_plan_run(runs: list[PlanRunRow], days: int) -> None:
    reader = InMemoryDiagnosticsReader([], runs)
    before = {**reader.stored(), "k2": None, "k3": None}

    report = service(reader).report(days=days)

    recent = [run for run in runs if run.created_at >= NOW - timedelta(days=days)]

    def broke(run: PlanRunRow) -> bool:
        return run.status == "failed" and run.failure_reason == "internal_invariant_violation"

    def omitted(run: PlanRunRow) -> bool:
        return run.status != "failed" and not set(run.included_item_ids) <= set(run.stop_item_ids)

    def counts(check: Any) -> dict[str, int]:
        return {"all_time": sum(map(check, runs)), "window": sum(map(check, recent))}

    after = {
        **reader.stored(),
        "k2": dict(report.k2.invariant_violations),
        "k3": dict(report.k3.report_omissions),
    }
    expected = {"k2": set_to(counts(broke)), "k3": set_to(counts(omitted))}
    assert_state_delta(before, after, {*STORED, "k2", "k3"}, expected, strict=True)


ENGINE_REASONS = {"routing_engine_unreachable", "routing_engine_not_ready"}
refusal_rows = st.builds(
    RefusalRow,
    project_id=st.sampled_from(list(PROJECTS)),
    reason=st.sampled_from(
        [*sorted(ENGINE_REASONS), "missing_anchor", "job_active", "optimizer_unavailable"],
    ),
    created_at=ages.map(lambda minutes: NOW - timedelta(minutes=minutes)),
)


@given(refusals=st.lists(refusal_rows, max_size=30), days=windows, chosen=st.sampled_from([None, "p1", "p2"]))
@settings(max_examples=100, deadline=None)
def test_g4_counts_the_refusals_for_the_engine_in_the_window_whatever_else_was_refused(
    refusals: list[RefusalRow], days: int, chosen: str | None
) -> None:
    reader = InMemoryDiagnosticsReader([], refusals=refusals)
    before = {**reader.stored(), "g4": None}

    report = service(reader).report(days=days, project_id=chosen)

    expected = sum(
        1
        for refusal in refusals
        if refusal.reason in ENGINE_REASONS
        and refusal.created_at >= NOW - timedelta(days=days)
        and chosen in (None, refusal.project_id)
    )
    after = {**reader.stored(), "g4": report.g4.engine_refusals}
    assert_state_delta(before, after, {*STORED, "g4"}, {"g4": set_to(expected)}, strict=True)


@given(project_id=st.text(min_size=1, max_size=12).filter(lambda name: name not in PROJECTS))
def test_an_unknown_project_is_refused_naming_it_and_nothing_changes(project_id: str) -> None:
    reader = InMemoryDiagnosticsReader([])
    before = {**reader.stored(), "refused": None}

    with pytest.raises(UnknownProjectError) as refused:
        service(reader).report(project_id=project_id)

    after = {**reader.stored(), "refused": refused.value.args}
    assert_state_delta(before, after, {*STORED, "refused"}, {"refused": set_to((project_id,))}, strict=True)
