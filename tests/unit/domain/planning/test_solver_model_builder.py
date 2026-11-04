"""The tour model of a trip (US-02b, brief sections 4 and 8): Start, End and one node per Included item.

Driving port: `SolverModelBuilder` (`required_pairs()` and `build(legs)` are its public interface).
Observable universe = the model's nodes and arcs as the solver reads them, the road pairs asked for, the snapshot read.
Test Budget: 3 behaviors (nodes, arc costs, required pairs) x 2 = 6; 3 used.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from hypothesis import given

from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder, TourModel
from tests.common.state_delta import assert_state_delta, set_to
from tests.unit.domain.planning.trips import Trip, left_at, reached_at, trips


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
