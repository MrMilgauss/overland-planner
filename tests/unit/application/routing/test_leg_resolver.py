"""The legs of a plan (brief section 8): what the leg resolver asks the road map for, and the table it hands back.

Driving ports: `LegResolver` from the routing facade, with the required pairs of the real `SolverModelBuilder`, and
`PlanJobRegistry` over the real `PlanRequestJob` for what a bad answer does to a job. Driven port: `RoutingProvider`
(recording double). Observable universe: `road_map.asked`, the pairs asked with their counts.
Test Budget: 2 behaviors (the required legs come from the road map, each distinct pair asked once; a row that does not
match its targets is refused, so no leg goes missing silently) x 2 = 4; 3 used.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from overland_planner.application.planning.facade import PlanJobRegistry, PlanRequestJob
from overland_planner.application.routing.facade import LegResolver
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import InMemoryPlanning, RecordingRoadMap, job_when_ended
from tests.unit.application.planning.scripted_tour_solver import ScriptedTourSolver
from tests.unit.domain.planning.trips import PROJECT, Trip, trips

UNIVERSE = {"road_map.asked"}
Row = list[int]
BUDGET = 500


def _view(road_map: RecordingRoadMap) -> dict[str, Any]:
    return {"road_map.asked": Counter(road_map.asked)}


@given(trip=trips())
def test_each_distinct_required_pair_is_asked_exactly_once_and_the_table_covers_them_all(trip: Trip) -> None:
    pairs = SolverModelBuilder(trip.snapshot).required_pairs()
    road_map = RecordingRoadMap(trip.leg_m)
    before = _view(road_map)

    table = LegResolver(road_map).resolve(pairs)

    distinct_roads = Counter(pair for pair in set(pairs) if pair[0] != pair[1])
    assert_state_delta(before, _view(road_map), UNIVERSE, {"road_map.asked": set_to(distinct_roads)}, strict=True)
    assert [table.distance_m(*pair) for pair in pairs] == [trip.road_m(*pair) for pair in pairs]


class _RoadMapAnsweringTheWrongShape(RecordingRoadMap):
    def __init__(self, trip: Trip, wrong_shape: Callable[[Row], Row]) -> None:
        super().__init__(trip.leg_m)
        self._wrong_shape = wrong_shape

    def matrix(self, sources: Sequence[Coordinate], targets: Sequence[Coordinate]) -> Sequence[Sequence[int]]:
        return [self._wrong_shape(list(row)) for row in super().matrix(sources, targets)]


def _one_leg_short(row: Row) -> Row:
    return row[:-1]


def _one_leg_too_many(row: Row) -> Row:
    return [*row, 1]


def _road_to_drive(trip: Trip) -> bool:
    return any(origin != destination for origin, destination in SolverModelBuilder(trip.snapshot).required_pairs())


@given(trip=trips(), wrong_shape=st.sampled_from((_one_leg_short, _one_leg_too_many)))
def test_a_row_that_does_not_match_its_targets_raises_instead_of_leaving_legs_out(
    trip: Trip, wrong_shape: Callable[[Row], Row]
) -> None:
    assume(_road_to_drive(trip))
    pairs = SolverModelBuilder(trip.snapshot).required_pairs()

    with pytest.raises(ValueError):
        LegResolver(_RoadMapAnsweringTheWrongShape(trip, wrong_shape)).resolve(pairs)


@settings(deadline=None)
@given(trip=trips(), wrong_shape=st.sampled_from((_one_leg_short, _one_leg_too_many)))
def test_a_job_whose_road_map_answers_a_row_of_the_wrong_shape_ends_failed_with_no_run(
    trip: Trip, wrong_shape: Callable[[Row], Row]
) -> None:
    assume(_road_to_drive(trip))
    planning = InMemoryPlanning()
    planning.add_project(PROJECT, trip.snapshot)
    solver = ScriptedTourSolver()
    clock = FakeClock()
    log = RecordingEventLog()
    files = InMemoryFileStore()
    trip.seed_canonical_files(files)
    road_map = _RoadMapAnsweringTheWrongShape(trip, wrong_shape)
    job = PlanRequestJob(planning.unit_of_work, LegResolver(road_map), solver, BUDGET, clock, log, files)
    registry = PlanJobRegistry(clock, job, log)

    job_id = registry.start(PROJECT)
    assert job_id is not None
    ended = job_when_ended(registry, job_id)

    assert (ended.state, ended.plan_run_id) == ("failed", None)
    assert planning.runs == [], "a bad road map answer stored a run"
    assert solver.models == [], "a bad road map answer reached the solver"
    (fields,) = log.fields_of("plan.job.finished")
    assert fields["error_class"] == "ValueError"
