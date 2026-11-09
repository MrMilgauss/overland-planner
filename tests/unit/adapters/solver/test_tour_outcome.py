"""What a solve child's messages and end mean (ADR-015 table of endings, D122 reason codes, D200 overrun).

Driving port: `tour_outcome(observation, model)`, a pure function (its signature is the interface), and
`incumbent_of(message, model)`, the one reading of a streamed incumbent the parent uses live and `tour_outcome` uses
after. For any sequence of child messages (valid and broken incumbents, a final with or without an order, anything
else) and any end of the child, the outcome is exactly one of: the final order ended by the budget, the last valid
incumbent ended by `optimizer_failed`, no route, failed (exit code or signal) or timeout.
Test Budget: 1 behavior (classifying a child's messages and end) x 2 = 2; 1 property test used. Expectations come from
how each observation was built (which messages were valid, how the child ended), not from re-deriving the rule.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.adapters.solver.ortools_tour_solver import TourChildObservation, incumbent_of, tour_outcome
from overland_planner.adapters.solver.tour_child import FINAL, INCUMBENT
from overland_planner.application.ports.tour_solver import Incumbent, TourOutcome
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {
    "outcome.reason",
    "outcome.order",
    "outcome.ending",
    "outcome.reproducible",
    "outcome.exit_code",
    "outcome.signal",
    "incumbents",
}
FAILED = "optimizer_failed"


def _expected(
    *,
    reason: str | None = None,
    order: tuple[str, ...] | None = None,
    ending: str | None = None,
    reproducible: bool | None = None,
    exit_code: int | None = None,
    signal: int | None = None,
    incumbents: tuple[Incumbent, ...] = (),
) -> dict[str, Any]:
    return {
        "outcome.reason": reason,
        "outcome.order": order,
        "outcome.ending": ending,
        "outcome.reproducible": reproducible,
        "outcome.exit_code": exit_code,
        "outcome.signal": signal,
        "incumbents": incumbents,
    }


def _observe(outcome: TourOutcome, incumbents: tuple[Incumbent, ...]) -> dict[str, Any]:
    return _expected(
        reason=getattr(outcome, "reason", None),
        order=getattr(outcome, "order", None),
        ending=getattr(outcome, "ending", None),
        reproducible=outcome.reproducible,
        exit_code=getattr(outcome, "exit_code", None),
        signal=getattr(outcome, "signal", None),
        incumbents=incumbents,
    )


def _model(item_count: int, *, round_trip: bool) -> TourModel:
    items = tuple(f"item-{number}" for number in range(item_count))
    start, end = ("base", "base") if round_trip else ("start", "end")
    size = item_count + 2
    return TourModel((start, *items, end), 0, size - 1, ((None,) * size,) * size)


models = st.builds(_model, st.integers(min_value=0, max_value=6), round_trip=st.booleans())
abnormal_exits = st.one_of(st.integers(min_value=-31, max_value=-1), st.integers(min_value=1, max_value=255))
objectives = st.one_of(st.integers(min_value=0, max_value=10**9), st.floats(0, 1e9, allow_nan=False))
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
        st.just(tour[::-1]) if model.start_node != model.end_node or len(tour) > 3 else st.just(tour[1:]),
        st.just((*tour[:-1], model.end_node + 1, tour[-1])),
        st.just((tour[0], *tour[:-1], tour[-1])),
        st.just(tuple(float(node) for node in tour)),
        st.just(tuple(str(node) for node in tour)),
        st.just(list(tour)),
        st.just(()),
        anything.filter(lambda value: value is not None and not isinstance(value, tuple)),
    )


def _ids(model: TourModel, tour: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(model.node_item_ids[node] for node in tour)


@st.composite
def _streams(draw: st.DrawFn, model: TourModel) -> tuple[list[Any], tuple[Incumbent, ...]]:
    """Messages the child sent before any final, and the valid incumbents among them in order."""
    sent: list[Any] = []
    valid: list[Incumbent] = []
    for _ in range(draw(st.integers(0, 4))):
        tour = draw(_complete_tours(model))
        objective = draw(objectives)
        kind = draw(st.sampled_from(["valid", "broken_tour", "wrong_shape", "anything"]))
        if kind == "valid":
            sent.append((INCUMBENT, tour, objective))
            valid.append(Incumbent(order=_ids(model, tour), objective=objective))
        elif kind == "broken_tour":
            sent.append((INCUMBENT, draw(_broken_tours(model, tour)), objective))
        elif kind == "wrong_shape":
            sent.append(draw(st.sampled_from([(INCUMBENT, tour), (INCUMBENT, tour, "far"), (INCUMBENT, tour, True)])))
        else:
            sent.append(draw(anything.filter(lambda value: not (isinstance(value, tuple) and value[:1] == (FINAL,)))))
    return sent, tuple(valid)


def _failure(exit_code: int | None, incumbents: tuple[Incumbent, ...]) -> dict[str, Any]:
    """An abnormal end: the last valid incumbent, labelled, or a Failed run with the exit code or signal."""
    if incumbents:
        return _expected(order=incumbents[-1].order, ending=FAILED, reproducible=False, incumbents=incumbents)
    if exit_code is not None and exit_code < 0:
        return _expected(reason=FAILED, reproducible=False, signal=-exit_code)
    return _expected(reason=FAILED, reproducible=False, exit_code=exit_code)


@st.composite
def child_ends(draw: st.DrawFn) -> tuple[TourChildObservation, TourModel, dict[str, Any]]:
    model = draw(models)
    tour = draw(_complete_tours(model))
    sent, valid = draw(_streams(model))
    final_tour = (FINAL, tour)
    any_exit = draw(st.one_of(st.none(), st.just(0), abnormal_exits))
    kind = draw(
        st.sampled_from(
            ["found", "no_route", "overrun", "abnormal_exit", "never_exited", "no_final", "bad_final", "lingered"]
        )
    )
    if kind == "found":
        expected = _expected(order=_ids(model, tour), ending="budget", reproducible=True, incumbents=valid)
        return TourChildObservation(0, (*sent, final_tour)), model, expected
    if kind == "no_route":
        expected = _expected(reason="no_valid_route_found", reproducible=True, incumbents=valid)
        return TourChildObservation(0, (*sent, (FINAL, None))), model, expected
    if kind == "lingered":  # a final, then a teardown the parent ended: the final counts
        ended_by_the_parent = draw(st.sampled_from([-15, -9, None]))
        observation = TourChildObservation(ended_by_the_parent, (*sent, final_tour), outlived_reap_wait=True)
        expected = _expected(order=_ids(model, tour), ending="budget", reproducible=True, incumbents=valid)
        return observation, model, expected
    if kind == "overrun":
        any_end = draw(st.sampled_from([(), (final_tour,)]))
        observation = TourChildObservation(any_exit, (*sent, *any_end), overran=True)
        return observation, model, _expected(reason="timeout", reproducible=False, incumbents=valid)
    if kind == "abnormal_exit":  # killed or crashed, whether or not its final made it
        exit_code = draw(abnormal_exits)
        any_end = draw(st.sampled_from([(), (final_tour,), ((FINAL, None),)]))
        return TourChildObservation(exit_code, (*sent, *any_end)), model, _failure(exit_code, valid)
    if kind == "never_exited":
        return TourChildObservation(None, tuple(sent)), model, _failure(None, valid)
    if kind == "no_final":  # pipe end-of-file after the incumbents, exit 0
        return TourChildObservation(0, tuple(sent)), model, _failure(0, valid)
    bad_final = draw(
        st.one_of(
            st.just((FINAL,)),
            st.just((FINAL, tour, None)),
            _broken_tours(model, tour).map(lambda broken: (FINAL, broken)),
        )
    )
    return TourChildObservation(0, (*sent, bad_final)), model, _failure(0, valid)


@given(case=child_ends())
def test_any_child_end_is_exactly_one_outcome(case: tuple[TourChildObservation, TourModel, dict[str, Any]]) -> None:
    observation, model, expected = case

    before = _expected()
    streamed = tuple(
        incumbent for message in observation.messages if (incumbent := incumbent_of(message, model)) is not None
    )
    after = _observe(tour_outcome(observation, model), streamed)

    assert_state_delta(before, after, UNIVERSE, {slot: set_to(value) for slot, value in expected.items()}, strict=True)
