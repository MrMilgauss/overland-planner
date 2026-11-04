"""Calculate's pre-checks and the plan run list (US-02b, brief §8).

Driving ports: `PlanRequestService` and `PlanRunQueries` from the planning facade, with the real `HealthService` holding
the start-up probe outcomes. Driven ports: `PlanningUnitOfWork` (in-memory double) and `EventLog` (recording double).
Observable universe: `plan_runs` as the queries show them, `jobs` handed out by `request` and `refusals_logged`.
Test Budget: 3 behaviors (a refusal is the first failing pre-check and changes nothing, an unknown project is not found,
the list shows the project's runs) x 2 = 6; 3 used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import ProjectNotFoundError
from overland_planner.application.planning.facade import PlanRefusedError, PlanRequestService, PlanRunQueries
from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.probe import ProbeOutcome, ProbeResult
from overland_planner.domain.planning.plan_run import PlanRun
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from tests.common.catalog_fakes import RecordingEventLog
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"plan_runs", "jobs", "refusals_logged"}
PROJECT = "project-1"
OUTCOMES = st.sampled_from(get_args(ProbeOutcome))
ANCHOR = st.none() | st.just("poi-1")
RUN_NUMBERS = st.sets(st.integers(min_value=1, max_value=50), max_size=5)


@dataclass
class InMemoryPlanning:
    """Stands for the database: a read-only view of the projects and the plan runs of each project."""

    snapshots: dict[str, ProjectSnapshot] = field(default_factory=dict)
    runs: dict[str, list[PlanRun]] = field(default_factory=dict)

    def unit_of_work(self) -> InMemoryPlanningUnitOfWork:
        return InMemoryPlanningUnitOfWork(self)

    def read(self, project_id: str) -> ProjectSnapshot | None:
        return self.snapshots.get(project_id)

    def list(self, project_id: str) -> list[PlanRun]:
        return sorted(self.runs.get(project_id, []), key=lambda run: run.number)


class InMemoryPlanningUnitOfWork:
    def __init__(self, planning: InMemoryPlanning) -> None:
        self.plan_runs = self.project_snapshots = planning

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        pass

    def commit(self) -> None:
        raise AssertionError("a pre-check or a query has nothing to commit")


def _planning(numbers: set[int], start: str | None = None, end: str | None = None) -> InMemoryPlanning:
    runs = [PlanRun(id=f"run-{number}", number=number, status="ready") for number in numbers]
    return InMemoryPlanning({PROJECT: ProjectSnapshot(start, end)}, {PROJECT: runs})


def _service(planning: InMemoryPlanning, solver: ProbeOutcome, other: ProbeOutcome = "ok") -> Any:
    health = HealthService({"tour_solver": ProbeResult(solver), "data_dir": ProbeResult(other)})
    log = RecordingEventLog()
    return PlanRequestService(planning.unit_of_work, health, log), log


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
    except NotImplementedError:  # every pre-check passed: no job until the plan job exists (step 04-04)
        return (), None


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
    logged = () if expected is None else (("plan.job.refused", _refusal_fields(expected)),)
    delta = {"refusals_logged": set_to(logged)}
    assert_state_delta(before, _view(planning, log, jobs), UNIVERSE, delta, strict=True)


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

    with pytest.raises(ProjectNotFoundError):
        PlanRunQueries(planning.unit_of_work).list(unknown)
    with pytest.raises(ProjectNotFoundError):
        service.request(unknown)

    assert_state_delta(before, _view(planning, log), UNIVERSE, {}, strict=True)


@given(numbers=RUN_NUMBERS, other_numbers=RUN_NUMBERS)
def test_the_list_shows_the_runs_of_that_project_only_and_changes_nothing(
    numbers: set[int], other_numbers: set[int]
) -> None:
    planning = _planning(numbers)
    planning.snapshots["project-2"] = ProjectSnapshot()
    planning.runs["project-2"] = [PlanRun(id=f"other-{n}", number=n, status="failed") for n in other_numbers]
    _, log = _service(planning, "ok")
    before = _view(planning, log)

    assert [run.number for run in PlanRunQueries(planning.unit_of_work).list(PROJECT)] == sorted(numbers)

    assert_state_delta(before, _view(planning, log), UNIVERSE, {}, strict=True)
