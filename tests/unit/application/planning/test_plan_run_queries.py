"""Stale plan runs (US-04 S4, brief section 8: a run is Stale when the project's revision is no longer the run's).

Driving port: `PlanRunQueries` from the planning facade. Driven port: `PlanningUnitOfWork` (in-memory double), whose
`ProjectSnapshotReader.stamp` gives the project's current revision and whose plan runs store the revision they were
computed at. Observable universe: `plan_runs` as stored and `projects` as planning reads them.
Test Budget: 3 behaviors (each listed run is stale iff its revision differs from the project's; a run's detail shows the
lines composed from its stored facts, an unreachable run naming its report's items, and `memo_hit` from its memo
source, the stored column for a run stored before 06-10; a project's Calculate notices follow its Included non-anchor
items) x 2 = 6; 3 used, none changes anything.
Every stale example holds both a current and a stale run, so both outcomes are checked each time (D212).
Mutant judged equivalent (07-12, slice 01b precedent): `None if source_id is None else get(source_id)` -> always
`get(source_id)` in `PlanRunQueries.get`: the repository answers `None` for a null id, as for any id it does not hold
(the adapter's `id IS NULL` on the primary key matches no row), so the source is `None` either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.application.planning.facade import PlanRunQueries
from overland_planner.application.ports.plan_run_repository import NewPlanRun
from overland_planner.application.ports.project_snapshot_reader import ProjectStamp
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.plan_run import PlanReport
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


@dataclass(frozen=True)
class Stored:
    """A stored run's facts: `run_time_ms` null for a run stored before 06-10, which keeps its `memo_hit` column."""

    status: str
    not_fully_optimised: str | None
    items: int
    run_time_ms: int | None
    from_source: bool
    memo_hit_column: bool
    cut_off: tuple[str, ...] | None  # a Failed `unreachable` run's report items; `()` is a report stored before 07-05


STORED = st.builds(
    Stored,
    status=st.sampled_from(("ready", "failed")),
    not_fully_optimised=st.sampled_from((None, "time_limit", "stopped", "optimizer_failed")),
    items=st.integers(min_value=0, max_value=80),
    run_time_ms=st.none() | st.integers(min_value=0, max_value=10_000_000),
    from_source=st.booleans(),
    memo_hit_column=st.booleans(),
    cut_off=st.none() | st.lists(st.sampled_from(("Valle Stretta", "Assietta")), unique=True, max_size=2).map(tuple),
)
LABEL = {"time_limit": "time limit", "stopped": "stopped", "optimizer_failed": "optimizer failed"}


def _stored_run(number: int, stored: Stored, source_id: str | None) -> NewPlanRun:
    ready = stored.status == "ready"
    return NewPlanRun(
        id=f"run-{number}",
        project_id=PROJECT,
        number=number,
        status="ready" if ready else "failed",
        failure_reason=None if ready else "no_valid_route_found" if stored.cut_off is None else "unreachable",
        report=None if ready or stored.cut_off is None else PlanReport("unreachable", stored.cut_off),
        created_at=datetime(2026, 11, 10, tzinfo=UTC),
        revision=1,
        provider_id="road-map-double",
        profile="4x4.v1",
        objective="distance",
        inputs={"included_item_ids": [f"item-{index}" for index in range(stored.items)]},
        stops=(),
        memo_hit=stored.memo_hit_column,
        reproducible=stored.not_fully_optimised is None,
        not_fully_optimised=stored.not_fully_optimised if ready else None,
        run_time_ms=stored.run_time_ms,
        memo_source_run_id=source_id,
    )


@settings(max_examples=60)
@given(stored=STORED, source_number=st.integers(min_value=1, max_value=50))
def test_a_run_shows_the_lines_of_its_stored_facts_and_a_memo_hit_names_its_source_by_number(
    stored: Stored, source_number: int
) -> None:
    planning = _planning(History(run_revisions=(), current=1))
    planning.seed_run(PROJECT, source_number)
    source_id = f"{PROJECT}-seeded-{source_number}" if stored.from_source else None
    planning.runs.append(_stored_run(source_number + 1, stored, source_id))
    before = _view(planning)

    detail = PlanRunQueries(planning.unit_of_work).get(f"run-{source_number + 1}")

    assert detail is not None
    ready, written_now = stored.status == "ready", stored.run_time_ms is not None
    reused = ready and stored.from_source
    expected = [
        *([f"Planned {stored.items} items in "] if ready and written_now else []),
        *(
            [f"not fully optimised ({LABEL[stored.not_fully_optimised]})"]
            if ready and stored.not_fully_optimised
            else []
        ),
        *([f"Reused the identical plan of run #{source_number}"] if reused else []),
        *(
            [
                f"Plan run #{source_number + 1} failed: '{name}' cannot be connected to any other stop at any "
                "confidence level"
                for name in stored.cut_off or ()
            ]
            if not ready
            else []
        ),
    ]
    shown = list(detail.messages)
    assert len(shown) == len(expected) and all(
        line.startswith(text) for line, text in zip(shown, expected, strict=True)
    )
    assert detail.memo_hit is (stored.from_source if written_now else stored.memo_hit_column)
    assert detail.provider_header == "Provider: road-map-double / profile: 4x4"
    assert_state_delta(before, _view(planning), UNIVERSE, {}, strict=True)


def _place(index: int, *, included: bool) -> PoiItem:
    here = Coordinate(45.0 + index / 1000, 7.0)
    return PoiItem(id=f"poi-{index}", project_id=PROJECT, name=f"Punto {index}", location=here, included=included)


@settings(max_examples=40)
@given(included=st.integers(min_value=0, max_value=90), left_out=st.integers(min_value=0, max_value=5))
def test_a_calculate_carries_the_large_project_notice_iff_more_than_sixty_items_are_included_between_the_anchors(
    included: int, left_out: int
) -> None:
    start, end = _place(-1, included=True), _place(-2, included=True)
    others = [_place(index, included=index < included) for index in range(included + left_out)]
    planning = InMemoryPlanning()
    planning.add_project(PROJECT, ProjectSnapshot(start.id, end.id, (start, end, *others)))
    before = _view(planning)

    notices = PlanRunQueries(planning.unit_of_work).notices(PROJECT)

    assert notices == (("Large project - calculation may take longer than 3 minutes",) if included > 60 else ())
    assert_state_delta(before, _view(planning), UNIVERSE, {}, strict=True)
