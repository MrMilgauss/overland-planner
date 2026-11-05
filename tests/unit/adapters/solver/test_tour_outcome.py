"""What a solve child's end means (ADR-015 D122 reason codes, D200 overrun).

Driving port: `tour_outcome(observation, model)`, a pure function (its signature is the interface). For any exit code
and any child message, including malformed ones, the outcome is exactly one of found, no route, failed or timeout.
Test Budget: 1 behavior (classifying a child's end) x 2 = 2; 1 property test used. Expectations come from how each
observation was built (a clean final tour, one injected fault), not from re-deriving the rule.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.adapters.solver.ortools_tour_solver import TourChildObservation, tour_outcome
from overland_planner.application.ports.tour_solver import TourOutcome
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {
    "outcome.reason",
    "outcome.order",
    "outcome.visited_item_ids",
    "outcome.exit_code",
    "outcome.signal",
}
FAILED = "optimizer_failed"


def _expected(
    *,
    reason: str | None = None,
    order: tuple[str, ...] | None = None,
    visited: tuple[str, ...] | None = None,
    exit_code: int | None = None,
    signal: int | None = None,
) -> dict[str, Any]:
    return {
        "outcome.reason": reason,
        "outcome.order": order,
        "outcome.visited_item_ids": visited,
        "outcome.exit_code": exit_code,
        "outcome.signal": signal,
    }


def _observe(outcome: TourOutcome) -> dict[str, Any]:
    return _expected(
        reason=getattr(outcome, "reason", None),
        order=getattr(outcome, "order", None),
        visited=getattr(outcome, "visited_item_ids", None),
        exit_code=getattr(outcome, "exit_code", None),
        signal=getattr(outcome, "signal", None),
    )


def _model(item_count: int, *, round_trip: bool) -> TourModel:
    items = tuple(f"item-{number}" for number in range(item_count))
    start, end = ("base", "base") if round_trip else ("start", "end")
    size = item_count + 2
    return TourModel((start, *items, end), 0, size - 1, ((None,) * size,) * size)


models = st.builds(_model, st.integers(min_value=0, max_value=6), round_trip=st.booleans())
abnormal_exits = st.one_of(st.integers(min_value=-31, max_value=-1), st.integers(min_value=1, max_value=255))
anything = st.recursive(
    st.one_of(
        st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.text(max_size=8), st.binary(max_size=8)
    ),
    lambda inner: st.lists(inner, max_size=3) | st.lists(inner, max_size=3).map(tuple),
    max_leaves=6,
)


def _complete_tours(model: TourModel) -> st.SearchStrategy[tuple[int, ...]]:
    inner = list(range(1, model.end_node))
    return st.permutations(inner).map(lambda middle: (model.start_node, *middle, model.end_node))


def _broken_tours(model: TourModel, tour: tuple[int, ...]) -> st.SearchStrategy[Any]:
    """Tuples of nodes that are not a tour of this model, and values that are not node tuples at all."""
    return st.one_of(
        st.just(tour[:-1]),
        st.just(tour[1:]),
        st.just(tour[::-1]),
        st.just((*tour[:-1], model.end_node + 1, tour[-1])),
        st.just((tour[0], *tour[:-1], tour[-1])),
        st.just(tuple(float(node) for node in tour)),
        st.just(tuple(str(node) for node in tour)),
        st.just(list(tour)),
        st.just(()),
        anything.filter(lambda value: value is not None and not isinstance(value, tuple)),
    )


def _failure_expected(exit_code: int) -> dict[str, Any]:
    if exit_code < 0:
        return _expected(reason=FAILED, signal=-exit_code)
    return _expected(reason=FAILED, exit_code=exit_code)


@st.composite
def child_ends(draw: st.DrawFn) -> tuple[TourChildObservation, TourModel, dict[str, Any]]:
    model = draw(models)
    tour = draw(_complete_tours(model))
    final_tour = ("final", tour)
    any_message = draw(st.one_of(st.just(final_tour), st.just(("final", None)), anything))
    any_exit = draw(st.one_of(st.none(), st.just(0), abnormal_exits))
    outlived = draw(st.booleans())
    kind = draw(
        st.sampled_from(
            [
                "found",
                "no_route",
                "overrun",
                "abnormal_exit",
                "never_exited",
                "bad_message",
                "found_then_lingered",
                "no_route_then_lingered",
                "bad_message_then_lingered",
            ]
        )
    )
    if kind == "found":
        ids = tuple(model.node_item_ids[node] for node in tour)
        return TourChildObservation(0, final_tour, False), model, _expected(order=ids, visited=ids[1:-1])
    if kind == "no_route":
        return TourChildObservation(0, ("final", None), False), model, _expected(reason="no_valid_route_found")
    if kind == "overrun":
        return TourChildObservation(any_exit, any_message, True, outlived), model, _expected(reason="timeout")
    if kind == "found_then_lingered":
        ids = tuple(model.node_item_ids[node] for node in tour)
        return TourChildObservation(any_exit, final_tour, False, True), model, _expected(order=ids, visited=ids[1:-1])
    if kind == "no_route_then_lingered":
        return (
            TourChildObservation(any_exit, ("final", None), False, True),
            model,
            _expected(reason="no_valid_route_found"),
        )
    if kind == "bad_message_then_lingered":
        ended_by_the_parent = draw(st.sampled_from([-15, -9]))
        lingering = TourChildObservation(ended_by_the_parent, ("incumbent", tour), False, True)
        return lingering, model, _failure_expected(ended_by_the_parent)
    if kind == "abnormal_exit":
        exit_code = draw(abnormal_exits)
        return TourChildObservation(exit_code, any_message, False), model, _failure_expected(exit_code)
    if kind == "never_exited":
        return TourChildObservation(None, any_message, False), model, _expected(reason=FAILED)
    bad_message = draw(
        st.one_of(
            anything.filter(lambda value: not (isinstance(value, tuple) and len(value) == 2)),
            st.just(("incumbent", tour)),
            st.just(("final",)),
            st.just(("final", tour, None)),
            _broken_tours(model, tour).map(lambda broken: ("final", broken)),
        )
    )
    return TourChildObservation(0, bad_message, False), model, _failure_expected(0)


@given(case=child_ends())
def test_any_child_end_is_exactly_one_outcome(case: tuple[TourChildObservation, TourModel, dict[str, Any]]) -> None:
    observation, model, expected = case

    before = _expected()
    after = _observe(tour_outcome(observation, model))

    assert_state_delta(before, after, UNIVERSE, {slot: set_to(value) for slot, value in expected.items()}, strict=True)
