"""Which Included items no order can connect (07-05, ADR-016 section 3, FR-8.2): the check before any solve.

Driving port: `unreachable_item_ids(model)`, a pure domain function (its signature is the interface). The model is a
plain matrix of arcs (`arc_m[a][b]` is `None` where no arc runs), as the builder writes it with retrace arcs included.
Observable universe: `unreachable` (the item ids reported, in node order). The oracle is a brute force on the matrix:
every simple path from a node is enumerated, so it shares no traversal with the production function. An item is reported
exactly when it has no arc in, no arc out, no path from the Start or no path to the End. The Start needs an arc out
only and the End an arc in only; a round trip names one place at both ends.
Test Budget: 1 behavior (the items reported are exactly those the brute force finds cut off) x 2 = 2; 1 used.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.planning.reachability import unreachable_item_ids
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"unreachable"}
Matrix = Sequence[Sequence[int | None]]


@st.composite
def models(draw: st.DrawFn) -> TourModel:
    """A model of k >= 0 items whose arcs are drawn at random, only where the builder may write one: from any node
    but the End to any node but the Start, never to itself, and Start to End only when no item is between."""
    items = draw(st.integers(0, 6))
    size = items + 2
    last = size - 1
    cells = [
        [
            draw(st.none() | st.integers(1, 10**6))
            if origin != last
            and destination != 0
            and origin != destination
            and (items == 0 or (origin, destination) != (0, last))
            else None
            for destination in range(size)
        ]
        for origin in range(size)
    ]
    ids = ["start", *(f"item-{i}" for i in range(items)), "start" if draw(st.booleans()) else "end"]
    return TourModel(tuple(ids), 0, last, tuple(tuple(row) for row in cells))


def _simple_paths(arcs: Matrix, source: int) -> Iterator[tuple[int, ...]]:
    """Every path from `source` that visits no node twice, the empty one included."""

    def extend(path: tuple[int, ...]) -> Iterator[tuple[int, ...]]:
        yield path
        for node, cell in enumerate(arcs[path[-1]]):
            if cell is not None and node not in path:
                yield from extend((*path, node))

    return extend((source,))


def _cut_off_by_brute_force(model: TourModel) -> tuple[str, ...]:
    arcs, last = model.arc_m, model.end_node
    from_start = {path[-1] for path in _simple_paths(arcs, model.start_node)}
    cut_off = []
    for node in range(1, last):
        arc_in = any(arcs[origin][node] is not None for origin in range(len(arcs)))
        arc_out = any(cell is not None for cell in arcs[node])
        reaches_end = any(path[-1] == last for path in _simple_paths(arcs, node))
        if not (arc_in and arc_out and node in from_start and reaches_end):
            cut_off.append(model.node_item_ids[node])
    return tuple(cut_off)


@given(model=models())
def test_the_items_reported_are_exactly_those_with_no_arc_in_no_arc_out_or_no_path_from_the_start_or_to_the_end(
    model: TourModel,
) -> None:
    assert_state_delta(
        {"unreachable": ()},
        {"unreachable": unreachable_item_ids(model)},
        UNIVERSE,
        {"unreachable": set_to(_cut_off_by_brute_force(model))},
        strict=True,
    )
