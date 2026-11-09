"""Stale plan runs (US-04 S4, brief section 8: a run is Stale when the project's revision is no longer the run's).

Driving port: `PlanRunQueries` from the planning facade. Driven port: `PlanningUnitOfWork` (in-memory double), whose
`ProjectSnapshotReader.stamp` gives the project's current revision and whose plan runs store the revision they were
computed at. Observable universe: `plan_runs` as stored and `projects` as planning reads them.
Test Budget: 1 behavior (each listed run is stale iff its revision differs from the project's, and listing changes
nothing) x 2 = 2; 1 used. Every example holds both a current and a stale run, so both outcomes are checked each time
(D212).
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.planning.facade import PlanRunQueries
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from tests.common.state_delta import assert_state_delta
from tests.unit.application.planning.planning_doubles import InMemoryPlanning

UNIVERSE = {"plan_runs", "projects"}
PROJECT = "project-1"
REVISION = st.integers(min_value=1, max_value=1_000)


@dataclass(frozen=True)
class History:
    """The revision each run was computed at, in run-number order, and the project's revision now."""

    run_revisions: tuple[int, ...]
    current: int


@st.composite
def histories(draw: st.DrawFn) -> History:
    current = draw(REVISION)
    fresh = draw(st.lists(st.just(current), min_size=1, max_size=3))
    stale = draw(st.lists(REVISION.filter(lambda revision: revision != current), min_size=1, max_size=4))
    return History(tuple(draw(st.permutations(fresh + stale))), current)


def _planning(history: History) -> InMemoryPlanning:
    planning = InMemoryPlanning()
    planning.add_project(PROJECT, ProjectSnapshot(), ProjectStamp(revision=history.current, objective="distance"))
    for number, revision in enumerate(history.run_revisions, start=1):
        planning.seed_run(PROJECT, number, revision=revision)
    return planning


def _view(planning: InMemoryPlanning) -> dict[str, object]:
    return {
        "plan_runs": (tuple(planning.runs), planning.commits),
        "projects": (dict(planning.snapshots), dict(planning.stamps)),
    }


@given(history=histories())
def test_a_run_is_stale_exactly_when_the_project_revision_moved_past_it(history: History) -> None:
    planning = _planning(history)
    before = _view(planning)

    listed = PlanRunQueries(planning.unit_of_work).list(PROJECT)

    assert [(run.number, run.stale) for run in listed] == [
        (number, revision != history.current) for number, revision in enumerate(history.run_revisions, start=1)
    ]
    assert_state_delta(before, _view(planning), UNIVERSE, {}, strict=True)
