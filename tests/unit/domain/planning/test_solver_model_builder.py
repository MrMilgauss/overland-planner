"""The tour model of a trip (US-02b, brief sections 4 and 8): Start, End and one node per Included item.

Driving port: `SolverModelBuilder` (`required_pairs()` and `build(legs)` are its public interface).
Observable universe = the model's nodes and arcs as the solver reads them, the road pairs asked for, the snapshot read,
and how the model describes an order (road metres, Unconfirmed legs, retraces: `counts_of`).
Test Budget: 6 behaviors (nodes, arc costs, required pairs, the lexicographic order over levels and retraces, weights
that keep it strict within an int64, criterion 2 alone) x 2 = 12; 7 used. The oracle of the order (`order_counts`)
reads the road map's answers and ranks orders by the tuple itself, never by the model's weights.

Mutation survivors judged equivalent (mutmut, 2026-11-11), none of them a behaviour:
- `_weights` mutants 5, 6, 11, 13 and `build` mutant 14 make W1 or W2 larger than the formula gives (`+ 2` for `+ 1`,
  one more arc): ADR-016 section 4 only bounds the weights from below and the int64 test has room to spare, so any
  larger weight is as right; the property below pins the lower bounds, with one arc of margin.
- `build` mutant 20 (`default=1` for a model with no arc): no arc is costed, so its weights are read by nobody.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise, permutations
from typing import Any, Literal

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import ArcTables, SolverModelBuilder, TourCounts, TourModel
from overland_planner.domain.routing.road_leg import LegTable, RoadLeg, RoadPair
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.domain.planning.trips import (
    POINT_PAIRS,
    PROJECT,
    Trip,
    left_at,
    reached_at,
    road_time_s,
    trips,
)


def _label(model: TourModel, node: int) -> str:
    if node == model.start_node:
        return "Start"
    if node == model.end_node:
        return "End"
    return model.node_item_ids[node]


def _arcs(model: TourModel) -> dict[tuple[str, str], int]:
    return {
        (_label(model, origin), _label(model, destination)): cost
        for origin, row in enumerate(model.arc_m)
        for destination, cost in enumerate(row)
        if cost is not None
    }


def _ends(trip: Trip) -> list[tuple[str, Any, Any]]:
    """Every item with the point it is reached at and the point it is left at, Start and End by their role."""
    return [(item.id, reached_at(item), left_at(item)) for item in trip.items]


def _built(trip: Trip, universe: set[str]) -> dict[str, Any]:
    model = SolverModelBuilder(trip.snapshot).build(trip.legs)
    observed = {
        "snapshot.read": trip.snapshot,
        "model.start_place": model.node_item_ids[model.start_node],
        "model.end_place": model.node_item_ids[model.end_node],
        "model.node_count": len(model.node_item_ids),
        "model.ends_are_two_nodes": model.start_node != model.end_node,
        "model.item_nodes": Counter(
            item_id
            for node, item_id in enumerate(model.node_item_ids)
            if node not in (model.start_node, model.end_node)
        ),
        "model.arcs": _arcs(model),
    }
    return {slot: observed[slot] for slot in universe}


def _before(trip: Trip, universe: set[str]) -> dict[str, Any]:
    return {slot: trip.snapshot if slot == "snapshot.read" else None for slot in universe}


@given(trip=trips())
def test_model_has_one_node_per_included_item(trip: Trip) -> None:
    universe = {
        "snapshot.read",
        "model.start_place",
        "model.end_place",
        "model.node_count",
        "model.ends_are_two_nodes",
        "model.item_nodes",
    }
    before = _before(trip, universe)

    after = _built(trip, universe)

    expected = {
        "model.start_place": set_to(trip.start.id),
        "model.end_place": set_to(trip.end.id),
        "model.node_count": set_to(len(trip.items) + 2),
        "model.ends_are_two_nodes": set_to(True),
        "model.item_nodes": set_to(Counter(item.id for item in trip.items)),
    }
    assert_state_delta(before, after, universe, expected, strict=True)


@given(trip=trips())
def test_arcs_run_from_exit_to_entry(trip: Trip) -> None:
    universe = {"snapshot.read", "model.arcs"}
    before = _before(trip, universe)

    after = _built(trip, universe)

    start, end = left_at(trip.start), reached_at(trip.end)
    costs = {
        (one, other): trip.road_m(left, reached)
        for one, _, left in _ends(trip)
        for other, reached, _ in _ends(trip)
        if one != other
    }
    costs |= {("Start", item): trip.road_m(start, reached) for item, reached, _ in _ends(trip)}
    costs |= {(item, "End"): trip.road_m(left, end) for item, _, left in _ends(trip)}
    if not trip.items:
        costs = {("Start", "End"): trip.road_m(start, end)}
    assert_state_delta(before, after, universe, {"model.arcs": set_to(costs)}, strict=True)


@given(trip=trips())
def test_required_pairs_are_k_squared_plus_k_or_the_single_start_to_end_pair(trip: Trip) -> None:
    universe = {"snapshot.read", "pairs.requested"}
    before = _before(trip, universe)

    after = {
        "snapshot.read": trip.snapshot,
        "pairs.requested": Counter(SolverModelBuilder(trip.snapshot).required_pairs()),
    }

    start, end = left_at(trip.start), reached_at(trip.end)
    pairs = Counter(
        (left, reached) for one, _, left in _ends(trip) for other, reached, _ in _ends(trip) if one != other
    )
    pairs.update((start, reached) for _, reached, _ in _ends(trip))
    pairs.update((left, end) for _, _, left in _ends(trip))
    if not trip.items:
        pairs = Counter({(start, end): 1})
    k = len(trip.items)
    assert sum(pairs.values()) == (k * k + k or 1)
    assert_state_delta(before, after, universe, {"pairs.requested": set_to(pairs)}, strict=True)


# --- Slice 03b, step 07-04: levels, no-road pairs, retrace arcs and the lexicographic order (FR-5.8, D148). ---

Level = Literal["confirmed", "unconfirmed"] | None  # None: no road at any level
LEVELS: tuple[Level, ...] = ("confirmed", "unconfirmed", None)
INT64_MAX = 2**63 - 1


@dataclass(frozen=True)
class RoadAnswers:
    """What the road map answers for every ordered pair of different points: metres and a level, or no road."""

    metres: dict[RoadPair, int]
    levels: dict[RoadPair, Level]

    def table(self) -> LegTable:
        legs = (
            RoadLeg(a, b, self.metres[a, b], road_time_s(self.metres[a, b]), level, _reason(level))
            for (a, b), level in self.levels.items()
            if level is not None
        )
        return LegTable(legs, no_road=[pair for pair, level in self.levels.items() if level is None])


def _reason(level: Level) -> str | None:
    return "no way to tell" if level == "unconfirmed" else None


def leg_counts(answers: RoadAnswers, previous: CatalogItem, successor: CatalogItem) -> tuple[int, int, int] | None:
    """The oracle's leg (Unconfirmed legs, retraces, road metres), or None where no leg may run: FR-5.8 and the
    retrace rule written out again from the road map's answers, independent of the model and of any weight."""
    left, reached = left_at(previous), reached_at(successor)
    if left == reached:
        return 0, 0, 0
    level = answers.levels[left, reached]
    if level is not None:
        return int(level == "unconfirmed"), 0, answers.metres[left, reached]
    if not isinstance(previous, TrackItem) or previous.entry == previous.exit:
        return None
    if previous.entry == reached:
        return 1, 1, 0  # the retrace counts as one Unconfirmed leg; nothing to drive from the entry
    onward = answers.levels[previous.entry, reached]
    if onward is None:
        return None
    return 1 + int(onward == "unconfirmed"), 1, answers.metres[previous.entry, reached]


def order_counts(answers: RoadAnswers, stops: Sequence[CatalogItem]) -> tuple[int, int, int] | None:
    """The oracle's (Unconfirmed legs, retraces, road metres) of driving `stops` in turn, or None if it cannot."""
    total = (0, 0, 0)
    for previous, successor in pairwise(stops):
        leg = leg_counts(answers, previous, successor)
        if leg is None:
            return None
        total = (total[0] + leg[0], total[1] + leg[1], total[2] + leg[2])
    return total


@dataclass(frozen=True)
class LevelledTrip:
    trip: Trip
    answers: RoadAnswers

    def model(self) -> TourModel:
        builder = SolverModelBuilder(self.trip.snapshot)
        return builder.build(self.answers.table())

    def orders(self) -> list[tuple[CatalogItem, ...]]:
        """Every order of the trip, Start and End included."""
        return [(self.trip.start, *order, self.trip.end) for order in permutations(self.trip.items)]


@st.composite
def levelled_trips(draw: st.DrawFn) -> LevelledTrip:
    """A generated trip whose road map answers each pair at a drawn level, or with no road."""
    trip = draw(trips())
    levels = {pair: draw(st.sampled_from(LEVELS)) for pair in POINT_PAIRS}
    return LevelledTrip(trip, RoadAnswers(dict(trip.leg_m), levels))


def nodes_of(model: TourModel, stops: Sequence[CatalogItem]) -> tuple[int, ...]:
    """The model's nodes for an order of stops (item ids are unique between the ends)."""
    inner = {item_id: node for node, item_id in enumerate(model.node_item_ids) if node not in (0, model.end_node)}
    return (model.start_node, *(inner[item.id] for item in stops[1:-1]), model.end_node)


def model_cost(model: TourModel, nodes: Sequence[int]) -> int | None:
    """What the solver minimises: the sum of the model's arc costs, None if an arc of the tour is missing."""
    costs = [model.arc_m[a][b] for a, b in pairwise(nodes)]
    return None if None in costs else sum(cost for cost in costs if cost is not None)


@given(levelled=levelled_trips())
def test_the_order_the_model_ranks_first_is_the_lexicographic_minimum(levelled: LevelledTrip) -> None:
    universe = {"model.drivable_orders", "model.described_orders", "model.first_ranked"}
    before = dict.fromkeys(universe)
    model = levelled.model()
    trip, answers = levelled.trip, levelled.answers
    stops = (trip.start, *trip.items, trip.end)
    legs = {(a.id, b.id): leg_counts(answers, a, b) for a in stops for b in stops}
    orders = [(trip.start.id, *(item.id for item in order), trip.end.id) for order in permutations(trip.items)]
    oracle = {order: _summed([legs[pair] for pair in pairwise(order)]) for order in orders}
    drivable = {order: counts for order, counts in oracle.items() if counts is not None}
    node = {item_id: index for index, item_id in enumerate(model.node_item_ids)}
    nodes = {order: (model.start_node, *(node[i] for i in order[1:-1]), model.end_node) for order in orders}
    costed = {order: model_cost(model, nodes[order]) for order in orders}

    ranked = min(((cost, order) for order, cost in costed.items() if cost is not None), default=None)
    after = {
        "model.drivable_orders": {order for order, cost in costed.items() if cost is not None},
        "model.described_orders": {order: model.counts_of(nodes[order]) for order in drivable},
        "model.first_ranked": None if ranked is None else oracle[ranked[1]],
    }

    expected = {
        "model.drivable_orders": set_to(set(drivable)),
        "model.described_orders": set_to({order: TourCounts(m, u, r) for order, (u, r, m) in drivable.items()}),
        "model.first_ranked": set_to(min(drivable.values()) if drivable else None),
    }
    assert_state_delta(before, after, universe, expected, strict=True)


def _summed(legs: Sequence[tuple[int, int, int] | None]) -> tuple[int, int, int] | None:
    if None in legs:
        return None
    return (sum(leg[0] for leg in legs if leg), sum(leg[1] for leg in legs if leg), sum(leg[2] for leg in legs if leg))


def _described(model: TourModel, order: Sequence[CatalogItem]) -> TourCounts | None:
    return model.counts_of(nodes_of(model, order))


@given(levelled=levelled_trips())
def test_weights_keep_the_order_strict_and_confirmed_arcs_keep_their_plain_metres(levelled: LevelledTrip) -> None:
    model = levelled.model()
    assert model.weights is not None and model.real is not None
    arcs = len(model.node_item_ids) - 1  # the arcs of one tour
    present = [(a, b) for a, row in enumerate(model.arc_m) for b, cost in enumerate(row) if cost is not None]
    c_max = max((model.real.road_m[a][b] or 0 for a, b in present), default=0)
    weights = model.weights

    assert weights.mode == "single_phase"
    assert weights.w2 > arcs * c_max, "no saving in metres buys an extra retrace"
    assert weights.w1 > arcs * (weights.w2 + c_max), "no saving in retraces or metres buys an Unconfirmed leg"
    assert weights.w2 > (arcs + 1) * c_max, "one arc of margin: a tour that gains an arc stays strict"
    assert weights.w1 > (arcs + 1) * (weights.w2 + c_max), "the same margin for the Unconfirmed legs"
    for a, row in enumerate(model.arc_m):
        for b, cost in enumerate(row):
            if cost is None:  # no arc runs: no metres, no Unconfirmed leg, no retrace (ArcTables)
                assert (model.real.road_m[a][b], model.real.unconfirmed_legs[a][b], model.real.retraces[a][b]) == (
                    None,
                    0,
                    0,
                )
    for a, b in present:
        unconfirmed, retraces = model.real.unconfirmed_legs[a][b], model.real.retraces[a][b]
        road = model.real.road_m[a][b]
        assert road is not None
        cost = model.arc_m[a][b]
        assert cost == weights.w1 * unconfirmed + weights.w2 * retraces + road, (a, b)
        assert cost is not None and cost <= INT64_MAX


def test_no_cost_overflows_int64_for_72_stops_with_legs_of_3000_km() -> None:
    # bypass: the extreme case is one fixed model (70 dead-end tracks, every leg 3,000 km and Unconfirmed); a property
    # over smaller models cannot reach the bound (the property above checks the weights' strictness on any model).
    far_m = 3_000_000
    start = PoiItem(id="start", project_id=PROJECT, name="Casa Marco", location=Coordinate(40.0, 0.0))
    end = PoiItem(id="end", project_id=PROJECT, name="Briancon", location=Coordinate(40.0, 0.5))
    tracks = [_dead_end(index) for index in range(70)]
    stops: tuple[CatalogItem, ...] = (start, *tracks, end)
    snapshot = ProjectSnapshot(start.id, end.id, stops)
    exits = {track.exit for track in tracks}
    points = {point for item in stops for point in (reached_at(item), left_at(item))} | {t.entry for t in tracks}
    pairs = [(a, b) for a in points for b in points if a != b]
    answers = RoadAnswers(
        dict.fromkeys(pairs, far_m), {(a, b): None if a in exits else "unconfirmed" for a, b in pairs}
    )

    model = SolverModelBuilder(snapshot).build(answers.table())

    costs = [cost for row in model.arc_m for cost in row if cost is not None]
    assert model.weights is not None and len(model.node_item_ids) == 72
    assert max(costs) == 2 * model.weights.w1 + model.weights.w2 + far_m, "a retrace with an Unconfirmed onward leg"
    assert (len(model.node_item_ids) - 1) * max(costs) <= INT64_MAX, "a whole tour's cost fits an int64"


def _dead_end(index: int) -> TrackItem:
    return TrackItem(
        id=f"track-{index}",
        project_id=PROJECT,
        name="Strada dell'Assietta",
        description=None,
        original_sha256="original",
        canonical_sha256="ab" * 32,
        direction_version=1,
        point_count=2,
        entry=Coordinate(41.0 + index / 100, 1.0),
        exit=Coordinate(42.0 + index / 100, 2.0),
        length_m=10_000.0,
    )


def test_with_equal_unconfirmed_legs_the_order_without_a_retrace_wins_over_a_shorter_one() -> None:
    # bypass: criterion 2 in isolation (FR-5.8 ruling 2026-11-10) needs one hand-made pair of orders; the scenario
    # 'An order with fewer retraces wins over a shorter order' is decided by criterion 1.
    s, a, b, p, e = (Coordinate(45.0 + i / 10, 7.0) for i in range(5))
    start = PoiItem(id="start", project_id=PROJECT, name="Casa Marco", location=s)
    poi = PoiItem(id="rifugio", project_id=PROJECT, name="Rifugio", location=p)
    end = PoiItem(id="end", project_id=PROJECT, name="Briancon", location=e)
    track = replace(_dead_end(0), id="assietta", entry=a, exit=b)
    km = 1000
    answers = RoadAnswers(
        metres={
            (s, a): 10 * km,
            (s, p): 10 * km,
            (b, p): 1,
            (a, p): 10 * km,
            (p, a): 40 * km,
            (b, e): 10 * km,
            (p, e): 10 * km,
        },
        levels={
            (s, a): "confirmed",
            (s, p): "confirmed",
            (b, p): None,
            (a, p): "confirmed",
            (p, a): "unconfirmed",
            (b, e): "confirmed",
            (p, e): "confirmed",
        },
    )
    snapshot = ProjectSnapshot(start.id, end.id, (start, track, poi, end))
    model = SolverModelBuilder(snapshot).build(answers.table())
    with_retrace, with_longer_road = (start, track, poi, end), (start, poi, track, end)

    described = {order: _described(model, order) for order in (with_retrace, with_longer_road)}
    costs = {order: model_cost(model, nodes_of(model, order)) for order in described}

    assert described == {
        with_retrace: TourCounts(road_m=30 * km, unconfirmed_legs=1, retraces=1),
        with_longer_road: TourCounts(road_m=60 * km, unconfirmed_legs=1, retraces=0),
    }, "same Unconfirmed legs; the order without a retrace is 30 km longer"
    winner = min(costs, key=lambda order: costs[order] or INT64_MAX)
    assert winner == with_longer_road


def test_an_order_that_names_no_tour_of_the_model_is_not_described() -> None:
    # bypass: a hand-made model whose tables hold an arc between every pair of nodes, so that only the order decides.
    cells = tuple((1, 1, 1) for _ in range(3))
    zeros = tuple((0, 0, 0) for _ in range(3))
    model = TourModel(("s", "a", "e"), 0, 2, cells, ArcTables(cells, zeros, zeros))

    described = {
        order: model.counts_of_order(order) for order in ((), ("s",), ("s", "no-such-item", "e"), ("s", "a", "e"))
    }

    assert described == {
        (): None,
        ("s",): None,
        ("s", "no-such-item", "e"): None,
        ("s", "a", "e"): TourCounts(road_m=2, unconfirmed_legs=0, retraces=0),
    }
