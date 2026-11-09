"""Calculate's pre-checks and the plan run list (US-02b, brief §8).

Driving ports: `PlanRequestService` and `PlanRunQueries` from the planning facade, with the real `HealthService` holding
the start-up probe outcomes. Driven ports: `PlanningUnitOfWork` (in-memory double) and `EventLog` (recording double).
Observable universe: `plan_runs` as the queries show them, `jobs` handed out by `request` and `refusals_logged`.
Test Budget: 3 behaviors (a refusal is the first failing pre-check and changes nothing, an unknown project is not found,
the list shows the project's runs) x 2 = 6; 3 used.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import ProjectNotFoundError
from overland_planner.application.planning.facade import (
    PlanJobProgress,
    PlanJobRegistry,
    PlanRefusedError,
    PlanRequestService,
    PlanRunQueries,
    StoredRun,
)
from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.probe import ProbeOutcome, ProbeResult
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from tests.common.catalog_fakes import RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import InMemoryPlanning

UNIVERSE = {"plan_runs", "jobs", "refusals_logged"}
PROJECT = "project-1"
OUTCOMES = st.sampled_from(get_args(ProbeOutcome))
ANCHOR = st.none() | st.just("poi-1")
RUN_NUMBERS = st.sets(st.integers(min_value=1, max_value=50), max_size=5)


def _planning(numbers: set[int], start: str | None = None, end: str | None = None) -> InMemoryPlanning:
    planning = InMemoryPlanning()
    planning.add_project(PROJECT, ProjectSnapshot(start, end))
    for number in numbers:
        planning.seed_run(PROJECT, number)
    return planning


class _NoWork:
    """Calculate's pre-checks are under test here; the plan job itself is in test_plan_job_registry.py."""

    def run(self, project_id: str, progress: PlanJobProgress, *, ignore_memo: bool = False) -> StoredRun:
        return StoredRun(plan_run_id="not-stored", reason=None)


def _service(planning: InMemoryPlanning, solver: ProbeOutcome, other: ProbeOutcome = "ok") -> Any:
    health = HealthService({"tour_solver": ProbeResult(solver), "data_dir": ProbeResult(other)})
    log = RecordingEventLog()
    jobs = PlanJobRegistry(FakeClock(), _NoWork(), RecordingEventLog())
    return PlanRequestService(planning.unit_of_work, health, log, jobs), log


def _view(planning: InMemoryPlanning, log: RecordingEventLog, jobs: tuple[Any, ...] = ()) -> dict[str, Any]:
    runs = PlanRunQueries(planning.unit_of_work).list(PROJECT)
    return {
        "plan_runs": tuple((run.id, run.number, run.status) for run in runs),
        "jobs": jobs,
        "refusals_logged": tuple(log.events),
    }


def _press_calculate(service: PlanRequestService) -> tuple[tuple[Any, ...], PlanRefusedError | None]:
    """The jobs handed out by one press, and its refusal."""
    try:
        return (service.request(PROJECT),), None
    except PlanRefusedError as refused:
        return (), refused


def _first_failing_pre_check(start: str | None, end: str | None, solver: ProbeOutcome) -> tuple[str, int, str] | None:
    if start is None:
        return "missing_anchor", 422, "Set the Start before calculating"
    if end is None:
        return "missing_anchor", 422, "Set the End before calculating"
    if solver != "ok":
        return "optimizer_unavailable", 503, "Optimizer unavailable - nothing was changed"
    return None


@given(start=ANCHOR, end=ANCHOR, solver=OUTCOMES, other=OUTCOMES, numbers=RUN_NUMBERS)
def test_a_refusal_is_the_first_failing_pre_check_in_brief_order_and_changes_nothing(
    start: str | None, end: str | None, solver: ProbeOutcome, other: ProbeOutcome, numbers: set[int]
) -> None:
    planning = _planning(numbers, start, end)
    service, log = _service(planning, solver, other)
    before = _view(planning, log)

    jobs, refused = _press_calculate(service)

    expected = _first_failing_pre_check(start, end, solver)
    seen = None if refused is None else (refused.reason, refused.http_status, str(refused))
    assert seen == expected
    if expected is None:
        assert_state_delta(before, _view(planning, log, jobs), UNIVERSE, {"jobs": _one_job_handed_out}, strict=True)
    else:
        logged = (("plan.job.refused", _refusal_fields(expected)),)
        delta = {"refusals_logged": set_to(logged)}
        assert_state_delta(before, _view(planning, log, jobs), UNIVERSE, delta, strict=True)


def _one_job_handed_out(_old: tuple[Any, ...], new: tuple[Any, ...]) -> bool:
    (job_id,) = new
    return isinstance(job_id, str) and job_id != ""


def _refusal_fields(refusal: tuple[str, int, str]) -> dict[str, object]:
    reason, http_status, _ = refusal
    return {"project_id": PROJECT, "http_status": http_status, "reason": reason}


@given(unknown=st.uuids().map(lambda u: u.hex), solver=OUTCOMES, numbers=RUN_NUMBERS)
def test_an_unknown_project_is_not_found_and_changes_nothing(
    unknown: str, solver: ProbeOutcome, numbers: set[int]
) -> None:
    planning = _planning(numbers, "poi-1", "poi-1")
    service, log = _service(planning, solver)
    before = _view(planning, log)

    with pytest.raises(ProjectNotFoundError) as listed:
        PlanRunQueries(planning.unit_of_work).list(unknown)
    with pytest.raises(ProjectNotFoundError) as requested:
        service.request(unknown)

    assert_state_delta(before, _view(planning, log), UNIVERSE, {}, strict=True)
    assert str(listed.value) == str(requested.value) == f"No project with id {unknown}", "the refusal names it"


@given(numbers=RUN_NUMBERS, other_numbers=RUN_NUMBERS)
def test_the_list_shows_the_runs_of_that_project_only_and_changes_nothing(
    numbers: set[int], other_numbers: set[int]
) -> None:
    planning = _planning(numbers)
    planning.add_project("project-2", ProjectSnapshot())
    for number in other_numbers:
        planning.seed_run("project-2", number, "failed")
    _, log = _service(planning, "ok")
    before = _view(planning, log)

    assert [run.number for run in PlanRunQueries(planning.unit_of_work).list(PROJECT)] == sorted(numbers)

    assert_state_delta(before, _view(planning, log), UNIVERSE, {}, strict=True)
