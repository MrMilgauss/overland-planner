"""The real OR-Tools child on models with levels and retrace arcs (slice 03b, 07-04; FR-5.8, ADR-016 s4, ADR-017).

Integration level, real spawned children. The oracle is the unit tests' `order_counts`, read from the road map's
answers and ranked by the tuple (Unconfirmed legs, retraces, road metres) itself, never by the model's weights. Up to 12
items an exact search over subsets (Held-Karp on the tuple, 12! orders being out of reach) gives the optimum.

Information only, not a test: the solve time of a sparse I2 variant next to I2's (dead ends at 10 percent of the
tracks, generated on the fly, never committed; single-phase weighting risk, decision 18):

    uv run python -m tests.integration.adapters.solver.test_ortools_tour_solver_retrace
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.clock.system_clock import SystemClock
from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.application.ports.tour_solver import Incumbent, SolveDeadlines, SolveLimits, TourFound
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot, left_at, reached_at
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg
from tests.unit.domain.planning.test_solver_model_builder import Level, RoadAnswers, leg_counts, order_counts
from tests.unit.domain.planning.trips import PROJECT

pytestmark = pytest.mark.solver_child

ENOUGH_BUDGET = 2_000
Counts = tuple[int, int, int]


def _limits() -> SolveDeadlines:
    clock = SystemClock()
    return SolveLimits().from_start(clock, clock.monotonic())


def _track(item_id: str, entry: Coordinate, exit_: Coordinate) -> TrackItem:
    return TrackItem(
        id=item_id,
        project_id=PROJECT,
        name="Strada dell'Assietta",
        description=None,
        original_sha256="original",
        canonical_sha256="ab" * 32,
        direction_version=1,
        point_count=2,
        entry=entry,
        exit=exit_,
        length_m=10_000.0,
    )


def _poi(item_id: str, location: Coordinate) -> PoiItem:
    return PoiItem(id=item_id, project_id=PROJECT, name="Rifugio", location=location)


def _road_m(a: Coordinate, b: Coordinate) -> int:
    """A made-up road: 1.3 times the flat distance, at least 1 m."""
    return max(1, round(1.3 * 111_000 * math.hypot(a.latitude - b.latitude, a.longitude - b.longitude)))


def _stops_of(snapshot: ProjectSnapshot, order: Sequence[str]) -> tuple[CatalogItem, ...]:
    return tuple(snapshot.item(item_id) for item_id in order)


def _exact_optimum(snapshot: ProjectSnapshot, answers: RoadAnswers) -> Counts | None:
    """Held-Karp over the items on the oracle's tuple (tuples add and compare as the lexicographic order needs)."""
    start, end, items = snapshot.start(), snapshot.end(), snapshot.visited_items()
    if not items:
        return leg_counts(answers, start, end)
    best: dict[tuple[int, int], Counts] = {}
    for index, item in enumerate(items):
        leg = leg_counts(answers, start, item)
        if leg is not None:
            best[1 << index, index] = leg
    for mask in range(1, 1 << len(items)):
        for last in range(len(items)):
            here = best.get((mask, last))
            if here is None:
                continue
            for following, item in enumerate(items):
                if mask & (1 << following):
                    continue
                leg = leg_counts(answers, items[last], item)
                if leg is None:
                    continue
                key = (mask | (1 << following), following)
                candidate = (here[0] + leg[0], here[1] + leg[1], here[2] + leg[2])
                if key not in best or candidate < best[key]:
                    best[key] = candidate
    full = (1 << len(items)) - 1
    finishes = []
    for last in range(len(items)):
        here, leg = best.get((full, last)), leg_counts(answers, items[last], end)
        if here is not None and leg is not None:
            finishes.append((here[0] + leg[0], here[1] + leg[1], here[2] + leg[2]))
    return min(finishes, default=None)


def _answers(points: set[Coordinate], level_of: dict[tuple[Coordinate, Coordinate], Level]) -> RoadAnswers:
    pairs = [(a, b) for a in points for b in points if a != b]
    return RoadAnswers(
        {pair: _road_m(*pair) for pair in pairs}, {pair: level_of.get(pair, "confirmed") for pair in pairs}
    )


def test_the_real_child_returns_the_lexicographic_optimum_and_its_incumbents_decode_to_the_oracle_counts() -> None:
    # Two dead-end trails and a place: from either trail's exit no road leaves, so each is retraced; one road leg
    # into the place is Unconfirmed.
    s, e = Coordinate(45.0, 7.0), Coordinate(45.0, 7.6)
    a1, b1, a2, b2, p = (
        Coordinate(45.1, 7.1),
        Coordinate(45.2, 7.15),
        Coordinate(45.1, 7.4),
        Coordinate(45.25, 7.45),
        Coordinate(44.95, 7.3),
    )
    start, end, place = _poi("start", s), _poi("end", e), _poi("rifugio", p)
    first, second = _track("assietta", a1, b1), _track("sommeiller", a2, b2)
    snapshot = ProjectSnapshot(start.id, end.id, (start, first, place, second, end))
    points = {s, e, a1, b1, a2, b2, p}
    level_of: dict[tuple[Coordinate, Coordinate], Level] = {(b, x): None for b in (b1, b2) for x in points}
    level_of[s, p] = "unconfirmed"
    answers = _answers(points, level_of)
    model = SolverModelBuilder(snapshot).build(answers.table())
    streamed: list[Incumbent] = []

    outcome = OrToolsTourSolver().solve(model, ENOUGH_BUDGET, on_incumbent=streamed.append, deadlines=_limits())

    assert isinstance(outcome, TourFound)
    assert order_counts(answers, _stops_of(snapshot, outcome.order)) == _exact_optimum(snapshot, answers)
    assert streamed, "the search reports its tours"
    for incumbent in streamed:
        unconfirmed, retraces, road_m = order_counts(answers, _stops_of(snapshot, incumbent.order)) or (-1, -1, -1)
        assert (incumbent.unconfirmed_legs, incumbent.retraces, incumbent.objective) == (unconfirmed, retraces, road_m)


@st.composite
def sparse_trips(draw: st.DrawFn) -> tuple[ProjectSnapshot, RoadAnswers]:
    """Up to 12 items at distinct points; some trails are dead ends, some exits lack roads, some legs Unconfirmed.
    A trail's entry always reaches every other point, so a retrace always exists and some tour always does."""
    rng = random.Random(draw(st.integers(0, 2**32)))  # noqa: S311 - reproducible test data, not security
    size = draw(st.integers(1, 12))

    def point() -> Coordinate:
        return Coordinate(round(44.0 + rng.random(), 6), round(6.5 + rng.random(), 6))

    start, end = _poi("start", point()), _poi("end", point())
    items: list[CatalogItem] = [
        _track(f"track-{i}", point(), point()) if rng.random() < 0.6 else _poi(f"poi-{i}", point()) for i in range(size)
    ]
    snapshot = ProjectSnapshot(start.id, end.id, (start, *items, end))
    points = {point for item in (start, *items, end) for point in (reached_at(item), left_at(item))}
    tracks = [item for item in items if isinstance(item, TrackItem)]
    dead_ends = {track.exit for track in tracks if rng.random() < 0.2}
    level_of: dict[tuple[Coordinate, Coordinate], Level] = {}
    for a in points:
        for b in points:
            from_an_exit = any(a == track.exit for track in tracks)
            if from_an_exit and (a in dead_ends or rng.random() < 0.3):
                level_of[a, b] = None
            elif rng.random() < 0.1:
                level_of[a, b] = "unconfirmed"
    return snapshot, _answers(points, level_of)


GAPS: list[float] = []


@settings(max_examples=20, deadline=None, derandomize=True)
@given(trip=sparse_trips())
def test_on_sparse_models_the_real_child_finds_the_fewest_unconfirmed_legs_and_retraces(
    trip: tuple[ProjectSnapshot, RoadAnswers],
) -> None:
    snapshot, answers = trip
    model = SolverModelBuilder(snapshot).build(answers.table())
    optimum = _exact_optimum(snapshot, answers)

    outcome = OrToolsTourSolver().solve(model, ENOUGH_BUDGET, deadlines=_limits())

    assert isinstance(outcome, TourFound) and optimum is not None
    found = order_counts(answers, _stops_of(snapshot, outcome.order))
    assert found is not None and found[:2] == optimum[:2], f"counts {found[:2] if found else None} vs {optimum[:2]}"
    gap = (found[2] - optimum[2]) / optimum[2] if optimum[2] else 0.0
    GAPS.append(gap)
    print(f"items={len(snapshot.visited_items())} counts={found[:2]} road km gap={gap:+.2%}")


def _sparse_i2_timing() -> None:
    from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider, read_road_map
    from tests.perf.golden_instances import COMMITTED, I2_SPARSE, SOLVER_BUDGET, committed_trip
    from tests.perf.reference_search import i1_model

    snapshot = i1_model(committed_trip(COMMITTED / f"{I2_SPARSE}.json")).snapshot
    road_map = MockRoutingProvider(script=read_road_map(COMMITTED / "i2-sparse.road-map.yaml"))
    tracks = [item for item in snapshot.visited_items() if isinstance(item, TrackItem)]
    dead_ends = {track.exit for track in random.Random(20261111).sample(tracks, max(1, len(tracks) // 10))}  # noqa: S311
    builder = SolverModelBuilder(snapshot)

    def table(pairs: Sequence[tuple[Coordinate, Coordinate]], cut: bool) -> LegTable:
        legs, no_road = [], []
        for origin, destination in dict.fromkeys(pairs):
            ((measure,),) = road_map.matrix([origin], [destination])
            if measure is None or (cut and origin in dead_ends):
                no_road.append((origin, destination))
            else:
                legs.append(RoadLeg(origin, destination, measure.distance_m, measure.duration_s))
        return LegTable(legs, no_road)

    first_pass = table(builder.required_pairs(), cut=True)
    sparse = builder.build(first_pass.merged_with(table(builder.retrace_pairs(first_pass), cut=False)))
    plain = builder.build(table(builder.required_pairs(), cut=False))
    for name, model in (("I2", plain), (f"I2 with {len(dead_ends)} dead ends", sparse)):
        streamed: list[Incumbent] = []
        began = time.monotonic()
        outcome = OrToolsTourSolver().solve(model, SOLVER_BUDGET, on_incumbent=streamed.append, deadlines=_limits())
        last = streamed[-1] if streamed else None
        counts = None if last is None else (last.unconfirmed_legs, last.retraces, round(last.objective / 1000, 1))
        print(f"{name}: {time.monotonic() - began:.1f} s, {type(outcome).__name__}, last (U, R, road km) {counts}")


if __name__ == "__main__":
    _sparse_i2_timing()
