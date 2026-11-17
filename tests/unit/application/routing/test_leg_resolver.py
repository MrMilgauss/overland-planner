"""The legs of a plan (brief section 8): what the leg resolver asks the road map for, and the table it hands back.

Driving ports: `LegResolver` from the routing facade, with the required pairs of the real `SolverModelBuilder`, and
`PlanJobRegistry` over the real `PlanRequestJob` for what a bad answer does to a job. Driven port: `RoutingProvider`
(recording double, and the offline road map `MockRoutingProvider` over an in-memory script, behind a counting spy).
Observable universe: `road_map.asked`, the pairs asked with their counts, and `plan.legs`, the distance and road time
the table hands to planning for each required pair; for the leg cache (06-09) also `road_map.calls_and_reports`, the
road map's calls and the resolver's reports of the legs found, in the order they happened.
Test Budget: 4 behaviors (the required legs come from the road map with distance and road time, each distinct pair
asked once; a scripted road map answers its script on listed pairs and straight line x detour factor at 60 km/h
elsewhere; a row that does not match its targets is refused, so no leg goes missing silently; the legs found are kept
per road map for the resolver's life and reported, the held ones before any call) x 2 = 8; 5 used.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Sequence
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider, RoadMapScript
from overland_planner.application.planning.facade import PlanJobRegistry, PlanRequestJob
from overland_planner.application.ports.routing_provider import RoutingObserver
from overland_planner.application.routing.facade import LegResolver, LegsFound
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from overland_planner.domain.routing.road_leg import LegTable, OffNetwork, RoadMeasure, RoadPair
from tests.common.catalog_fakes import InMemoryFileStore, RecordingEventLog
from tests.common.fakes import FakeClock
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.application.planning.planning_doubles import InMemoryPlanning, RecordingRoadMap, job_when_ended
from tests.unit.application.planning.scripted_tour_solver import ScriptedTourSolver
from tests.unit.domain.planning.trips import POINT_PAIRS, POINTS, PROJECT, Trip, trips

UNIVERSE = {"road_map.asked", "plan.legs"}
Row = list[RoadMeasure]
BUDGET = 500
DETOUR_FACTOR = 1.3
METRES_PER_SECOND_AT_60_KMH = 60 / 3.6


def _view(asked: Counter[RoadPair], table: LegTable | None, pairs: Sequence[RoadPair]) -> dict[str, Any]:
    legs = {} if table is None else {pair: (table.distance_m(*pair), table.duration_s(*pair)) for pair in pairs}
    return {"road_map.asked": Counter(asked), "plan.legs": legs}


def _distinct_roads(pairs: Sequence[RoadPair]) -> Counter[RoadPair]:
    return Counter(pair for pair in set(pairs) if pair[0] != pair[1])


@given(trip=trips())
def test_each_distinct_required_pair_is_asked_exactly_once_and_the_table_carries_its_distance_and_road_time(
    trip: Trip,
) -> None:
    pairs = SolverModelBuilder(trip.snapshot).required_pairs()
    leg_s = {pair: metres // 7 + 11 for pair, metres in trip.leg_m.items()}  # unlike the metres, so no field swaps
    road_map = RecordingRoadMap(trip.leg_m, leg_s=leg_s)
    before = _view(road_map.asked, None, pairs)

    table = LegResolver(road_map).resolve(pairs)

    expected_legs = {pair: (trip.road_m(*pair), 0 if pair[0] == pair[1] else leg_s[pair]) for pair in pairs}
    assert_state_delta(
        before,
        _view(road_map.asked, table, pairs),
        UNIVERSE,
        {"road_map.asked": set_to(_distinct_roads(pairs)), "plan.legs": set_to(expected_legs)},
        strict=True,
    )


class _CountingRoadMap:
    """Spy in front of a road map: `asked` counts every pair the resolver asked for."""

    def __init__(self, road_map: MockRoutingProvider) -> None:
        self._road_map = road_map
        self.provider_id = road_map.provider_id
        self.profile = road_map.profile
        self.asked: Counter[RoadPair] = Counter()

    def probe(self) -> Any:
        return self._road_map.probe()

    def matrix(
        self, sources: Sequence[Coordinate], targets: Sequence[Coordinate], observer: RoutingObserver | None = None
    ) -> Sequence[Sequence[RoadMeasure]]:
        self.asked.update((source, target) for source in sources for target in targets)
        return self._road_map.matrix(sources, targets)


alpine_points = st.builds(
    Coordinate,
    st.floats(44.0, 46.5).map(lambda lat: round(lat, 6)),
    st.floats(6.5, 8.5).map(lambda lon: round(lon, 6)),
)


@st.composite
def scripted_trips(draw: st.DrawFn) -> tuple[list[RoadPair], dict[RoadPair, RoadMeasure]]:
    """Required pairs over Alpine points, with a script over some of them: every example has a listed pair, an
    unlisted pair between distinct points and a pair of identical points (D212)."""
    points = draw(st.lists(alpine_points, min_size=3, max_size=6, unique=True))
    roads = draw(st.lists(st.sampled_from(points), min_size=2, max_size=2, unique=True).map(tuple))
    others = draw(st.lists(st.tuples(st.sampled_from(points), st.sampled_from(points)), max_size=12))
    pairs: list[RoadPair] = [roads, (roads[1], roads[0]), (points[2], points[2]), *others]  # type: ignore[list-item]
    listed = [roads, *draw(st.lists(st.sampled_from([p for p in pairs[3:] if p[0] != p[1]] or [roads])))]
    measure = st.builds(RoadMeasure, st.integers(1, 900_000), st.integers(1, 60_000))
    script = {pair: draw(measure) for pair in listed if pair != (roads[1], roads[0])}
    return draw(st.permutations(pairs)), script


def _straight_line_default(origin: Coordinate, destination: Coordinate) -> tuple[int, int]:
    """Brief section 6 and D220 f: straight line x 1.3, driven at 60 km/h; nothing to drive between identical points."""
    if origin == destination:
        return 0, 0
    metres = max(1, round(origin.great_circle_distance_m(destination) * DETOUR_FACTOR))
    return metres, max(1, round(metres / METRES_PER_SECOND_AT_60_KMH))


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(case=scripted_trips())
def test_a_scripted_road_map_answers_its_script_on_listed_pairs_and_the_default_elsewhere(
    case: tuple[list[RoadPair], dict[RoadPair, RoadMeasure]],
) -> None:
    pairs, script = case
    road_map = _CountingRoadMap(MockRoutingProvider(script=RoadMapScript(DETOUR_FACTOR, script, "sha256-of-script")))
    before = _view(road_map.asked, None, pairs)

    table = LegResolver(road_map).resolve(pairs)

    expected_legs = {
        pair: (script[pair].distance_m, script[pair].duration_s) if pair in script else _straight_line_default(*pair)
        for pair in pairs
    }
    after = _view(road_map.asked, table, pairs)
    assert_state_delta(
        before,
        after,
        UNIVERSE,
        {"road_map.asked": set_to(_distinct_roads(pairs)), "plan.legs": set_to(expected_legs)},
        strict=True,
    )
    assert all((0 in legs) == (pair[0] == pair[1]) for pair, legs in after["plan.legs"].items()), "0 m or 0 s apart"


class _RoadMapAnsweringTheWrongShape(RecordingRoadMap):
    def __init__(self, trip: Trip, wrong_shape: Callable[[Row], Row]) -> None:
        super().__init__(trip.leg_m)
        self._wrong_shape = wrong_shape

    def matrix(
        self, sources: Sequence[Coordinate], targets: Sequence[Coordinate], observer: RoutingObserver | None = None
    ) -> Sequence[Sequence[RoadMeasure]]:
        return [self._wrong_shape(list(row)) for row in super().matrix(sources, targets)]


def _one_leg_short(row: Row) -> Row:
    return row[:-1]


def _one_leg_too_many(row: Row) -> Row:
    return [*row, RoadMeasure(1, 1)]


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


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
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


# ------------------------------------------------------------------- the leg cache (06-09: US-06b S3, D43, ADR-015)
CACHE_UNIVERSE = {"road_map.asked", "plan.legs", "road_map.calls_and_reports"}
ROAD_MAPS = (  # road maps that differ in provider id or in profile: legs are held per (provider_id, profile)
    ("road-map-a", "profile-a"),
    ("road-map-a", "profile-b"),
    ("road-map-b", "profile-a"),
)


class _RoadMapOfManyNames(RecordingRoadMap):
    """A recording road map whose provider_id the test sets; `events` lists its calls and the resolver's reports."""

    def __init__(self, trip: Trip, no_road: Collection[RoadPair] = ()) -> None:
        leg_s = {pair: metres // 7 + 11 for pair, metres in trip.leg_m.items()}
        super().__init__(trip.leg_m, leg_s=leg_s, no_road=no_road)
        self.provider_id, self.profile = ROAD_MAPS[0]
        self.events: list[tuple[Any, ...]] = []

    def matrix(
        self, sources: Sequence[Coordinate], targets: Sequence[Coordinate], observer: RoutingObserver | None = None
    ) -> Sequence[Sequence[RoadMeasure]]:
        self.events.append(("asked", tuple((source, target) for source in sources for target in targets)))
        return super().matrix(sources, targets)

    def reported(self, found: LegsFound) -> None:
        self.events.append(("found", found.new, found.cached, found.total))


def _expected_calls_and_reports(pairs: Sequence[RoadPair], held: set[RoadPair]) -> list[tuple[Any, ...]]:
    """One call per origin with all its missing targets (L5), in the order the origins first appear; the held legs
    are reported before any call and the legs found after every call."""
    distinct = list(dict.fromkeys(pairs))
    missing: dict[Coordinate, list[RoadPair]] = {}
    for pair in distinct:
        if pair[0] != pair[1] and pair not in held:
            missing.setdefault(pair[0], []).append(pair)
    total, cached = len(distinct), len(distinct) - sum(map(len, missing.values()))
    events: list[tuple[Any, ...]] = [("found", 0, cached, total)]
    new = 0
    for asked in missing.values():
        new += len(asked)
        events += [("asked", tuple(asked)), ("found", new, cached, total)]
    return events


requests = st.lists(
    st.tuples(st.sampled_from(ROAD_MAPS), st.lists(st.sampled_from([*POINT_PAIRS, *((p, p) for p in POINTS)]))),
    min_size=1,
    max_size=6,
)


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(trip=trips(), sequence=requests)
def test_the_legs_found_are_kept_per_road_map_and_only_the_missing_ones_are_asked_after_the_held_ones_are_reported(
    trip: Trip, sequence: list[tuple[tuple[str, str], list[RoadPair]]]
) -> None:
    road_map = _RoadMapOfManyNames(trip)
    resolver = LegResolver(road_map)
    held: dict[tuple[str, str], set[RoadPair]] = {key: set() for key in ROAD_MAPS}  # the model of the cache
    for road_map_key, pairs in sequence:
        road_map.provider_id, road_map.profile = road_map_key
        road_map.events.clear()
        before = {**_view(road_map.asked, None, pairs), "road_map.calls_and_reports": []}

        table = resolver.resolve(pairs, road_map.reported)

        expected_events = _expected_calls_and_reports(pairs, held[road_map_key])
        newly_asked = [pair for event in expected_events if event[0] == "asked" for pair in event[1]]
        expected_legs = {pair: (trip.road_m(*pair), 0 if pair[0] == pair[1] else pair_s(trip, pair)) for pair in pairs}
        assert_state_delta(
            before,
            {**_view(road_map.asked, table, pairs), "road_map.calls_and_reports": list(road_map.events)},
            CACHE_UNIVERSE,
            {
                "road_map.asked": lambda old, new, asked=Counter(newly_asked): new - old == asked and old <= new,
                "plan.legs": set_to(expected_legs),
                "road_map.calls_and_reports": set_to(expected_events),
            },
            strict=True,
        )
        held[road_map_key].update(newly_asked)


def pair_s(trip: Trip, pair: RoadPair) -> int:
    return trip.leg_m[pair] // 7 + 11


# ------------------------------------------------------------------- pairs with no road (07-03, ADR-017 section 2)
NO_ROAD_UNIVERSE = {"road_map.asked", "plan.connected", "road_map.calls_and_reports"}


@given(trip=trips(), sequence=requests, no_road=st.sets(st.sampled_from(POINT_PAIRS)))
def test_a_pair_with_no_road_is_known_as_such_asked_once_per_road_map_and_counted_like_any_leg(
    trip: Trip, sequence: list[tuple[tuple[str, str], list[RoadPair]]], no_road: set[RoadPair]
) -> None:
    road_map = _RoadMapOfManyNames(trip, no_road)
    resolver = LegResolver(road_map)
    held: dict[tuple[str, str], set[RoadPair]] = {key: set() for key in ROAD_MAPS}
    for road_map_key, pairs in sequence:
        road_map.provider_id, road_map.profile = road_map_key
        road_map.events.clear()
        before = {"road_map.asked": Counter(road_map.asked), "plan.connected": {}, "road_map.calls_and_reports": []}

        table = resolver.resolve(pairs, road_map.reported)

        expected_events = _expected_calls_and_reports(pairs, held[road_map_key])
        newly_asked = [pair for event in expected_events if event[0] == "asked" for pair in event[1]]
        *_, (_, new, cached, total) = [event for event in road_map.events if event[0] == "found"]
        assert new + cached == total == len(set(pairs)), "the legs counters add up at the end"
        assert_state_delta(
            before,
            {
                "road_map.asked": Counter(road_map.asked),
                "plan.connected": {pair: table.connected(*pair) for pair in pairs},
                "road_map.calls_and_reports": list(road_map.events),
            },
            NO_ROAD_UNIVERSE,
            {
                "road_map.asked": lambda old, new, asked=Counter(newly_asked): new - old == asked and old <= new,
                "plan.connected": set_to({pair: pair[0] == pair[1] or pair not in no_road for pair in pairs}),
                "road_map.calls_and_reports": set_to(expected_events),
            },
            strict=True,
        )
        held[road_map_key].update(newly_asked)


# ------------------------------------------------- places the road map cannot snap (slice 06a, D245, ADR-013 Amend. 4)
class _FarPlaceRoadMap(RecordingRoadMap):
    """A road map for which `far` places lie off the network: every pair from or to one answers an `OffNetwork` naming
    the far end or ends of that pair. `calls` lists each call's origin and targets."""

    profile = "far-places"

    def __init__(self, trip: Trip, far: frozenset[Coordinate]) -> None:
        super().__init__(trip.leg_m)
        self._far = far
        self.calls: list[tuple[Coordinate, tuple[Coordinate, ...]]] = []

    def matrix(
        self, sources: Sequence[Coordinate], targets: Sequence[Coordinate], observer: RoutingObserver | None = None
    ) -> Sequence[Sequence[RoadMeasure | OffNetwork]]:
        self.calls.extend((source, tuple(targets)) for source in sources)
        return [[self._cell(source, target) for target in targets] for source in sources]

    def _cell(self, source: Coordinate, target: Coordinate) -> RoadMeasure | OffNetwork:
        named = frozenset({source, target}) & self._far
        return OffNetwork(named) if named else RoadMeasure(self._leg_m[source, target], 60)


@given(
    trip=trips(),
    far=st.frozensets(st.sampled_from(POINTS), max_size=3),
    pairs=st.lists(st.sampled_from(POINT_PAIRS), min_size=1, max_size=40),
)
def test_a_place_off_the_network_is_asked_once_per_request_has_no_road_counts_as_found_and_is_never_kept(
    trip: Trip, far: frozenset[Coordinate], pairs: list[RoadPair]
) -> None:
    road_map = _FarPlaceRoadMap(trip, far)
    resolver = LegResolver(road_map)
    distinct = set(pairs)
    far_pairs = {pair for pair in distinct if far & set(pair)}
    for request in (1, 2):
        road_map.calls.clear()
        heard: list[LegsFound] = []

        table = resolver.resolve(pairs, heard.append)

        view = {
            "plan.connected": {pair: table.connected(*pair) for pair in distinct},
            "legs.final": (heard[-1].new, heard[-1].cached, heard[-1].total),
            "road_map.calls_about_a_far_place": {
                place: sum(place in {origin, *targets} for origin, targets in road_map.calls) for place in far
            },
        }
        assert_state_delta(
            {"plan.connected": {}, "legs.final": None, "road_map.calls_about_a_far_place": {}},
            view,
            {"plan.connected", "legs.final", "road_map.calls_about_a_far_place"},
            {
                "plan.connected": set_to({pair: pair not in far_pairs for pair in distinct}),
                # the first request asks everything; the second finds every answered pair in the cache
                "legs.final": set_to(
                    (len(distinct), 0, len(distinct))
                    if request == 1
                    else (len(far_pairs), len(distinct) - len(far_pairs), len(distinct))
                ),
                "road_map.calls_about_a_far_place": lambda _, new: all(count <= 1 for count in new.values()),
            },
            strict=True,
        )
        assert bool(far_pairs) == any(view["road_map.calls_about_a_far_place"].values()), "a far place is asked again"
