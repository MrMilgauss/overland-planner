"""What a solve child's messages and end mean (ADR-015 table of endings, D122 reason codes, D200 limits, D58).

Driving ports: `tour_outcome(observation, model)`, a pure function (its signature is the interface),
`incumbent_of(message, model)`, the one reading of a streamed incumbent the parent uses live and `tour_outcome` uses
after, and `read_tour_child(receiver, deadlines, model, on_incumbent)`, the parent's reading of the child's pipe against
the deadlines on the `Clock` port. For any sequence of child messages (valid and broken incumbents, a final with or
without an order, anything else) and any end of the child, the outcome is exactly one of: the final order ended by the
budget, the last valid incumbent ended by `optimizer_failed` or by `time_limit`, no route, failed (exit code or signal)
or timeout. For any timeline of a child's messages against a fake clock (when each incumbent and the final arrive, when
the solve starts after the job did, the two deadlines), the reading ends exactly at the final, at the feasibility
deadline without an incumbent (timeout) or at the optimisation deadline with one (time_limit, the last incumbent).
Test Budget: 2 behaviors (classifying a child's messages and end; ending the reading at the limit that applies) x 2 = 4;
2 property tests used. Expectations come from how each observation or timeline was built (which messages were valid,
how the child ended, which instants fall before which deadline), not from re-deriving the rule.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.adapters.solver.ortools_tour_solver import (
    TourChildObservation,
    incumbent_of,
    read_tour_child,
    tour_outcome,
)
from overland_planner.adapters.solver.tour_child import FINAL, INCUMBENT
from overland_planner.application.ports.tour_solver import Incumbent, SolveLimits, TourOutcome
from overland_planner.domain.planning.solver_model_builder import TourModel
from tests.common.fakes import FakeClock
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
    if kind == "overrun":  # the limit that applies came first: the last valid incumbent, or a Failed timeout
        observation = TourChildObservation(any_exit, tuple(sent), overran=True)
        if valid:
            expected = _expected(order=valid[-1].order, ending="time_limit", reproducible=False, incumbents=valid)
            return observation, model, expected
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


# ------------------------------------------------------------------------------------- the limits from job start
TICK_S = 1 / 16  # every instant is an odd number of ticks, so none falls on a whole-second deadline; exact in binary
PARENT_ENDED_IT = -15  # the parent ends an overrunning child with SIGTERM first
TIMELINE_UNIVERSE = UNIVERSE | {"ended_at_s"}


class TimelinePipe:
    """The parent's end of a child's pipe on a fake clock: each message arrives at its instant, then the pipe ends at
    `ends_at_s` (`None`: a hung child that never closes it). A wait moves the clock to the arrival or by the timeout."""

    def __init__(self, clock: FakeClock, arrivals: list[tuple[float, Any]], ends_at_s: float | None) -> None:
        self._clock = clock
        self._arrivals = list(arrivals)
        self._ends_at_s = ends_at_s

    def _next_at(self) -> float | None:
        return self._arrivals[0][0] if self._arrivals else self._ends_at_s

    def poll(self, timeout: float) -> bool:
        now, next_at = self._clock.monotonic(), self._next_at()
        if next_at is not None and next_at <= now + timeout:
            self._clock.advance(max(0.0, next_at - now))
            return True
        self._clock.advance(timeout)
        return False

    def recv(self) -> Any:
        if not self._arrivals:
            raise EOFError
        return self._arrivals.pop(0)[1]


def _odd_ticks(low_s: float, high_s: float) -> st.SearchStrategy[float]:
    """An instant strictly between two instants (seconds from job start), an odd number of ticks."""
    low, high = int(low_s / TICK_S), int(high_s / TICK_S)
    return (
        st.integers(low, high)
        .map(lambda n: n | 1)
        .filter(lambda n: low_s < n * TICK_S < high_s)
        .map(lambda n: n * TICK_S)
    )


@st.composite
def timelines(draw: st.DrawFn) -> tuple[SolveLimits, float, TourModel, list[tuple[float, Any]], float | None, dict]:
    """Limits, the solve's start (after the legs), a child's arrivals and pipe end, and the ending they must give."""
    feasibility = draw(st.integers(1, 20))
    optimisation = draw(st.integers(feasibility, 40))
    limits = SolveLimits(feasibility_s=feasibility, optimisation_s=optimisation)
    model = draw(models)
    solve_starts_at = draw(st.integers(0, feasibility * 16 - 2)) * TICK_S  # the legs took this long
    kind = draw(st.sampled_from(["budget", "time_limit", "timeout", "no_route"]))

    def incumbent_at(after_s: float, before_s: float) -> tuple[float, Any, Incumbent]:
        at = draw(_odd_ticks(after_s, before_s))
        tour, objective = draw(_complete_tours(model)), draw(objectives)
        return at, (INCUMBENT, tour, objective), Incumbent(order=_ids(model, tour), objective=objective)

    arrivals: list[tuple[float, Any]] = []
    read: list[Incumbent] = []
    if kind in ("budget", "time_limit"):
        at, message, incumbent = incumbent_at(solve_starts_at, feasibility)  # the first one in time
        arrivals.append((at, message))
        read.append(incumbent)
    if kind == "budget":
        for _ in range(draw(st.integers(0, 3))):
            at, message, incumbent = incumbent_at(arrivals[-1][0], optimisation)
            arrivals.append((at, message))
            read.append(incumbent)
        final_at = draw(_odd_ticks(arrivals[-1][0], optimisation))
        final_tour = draw(_complete_tours(model))
        arrivals.append((final_at, (FINAL, final_tour)))
        expected = _expected(order=_ids(model, final_tour), ending="budget", reproducible=True, incumbents=tuple(read))
        return limits, solve_starts_at, model, arrivals, final_at, {**expected, "ended_at_s": final_at}
    if kind == "no_route":
        final_at = draw(_odd_ticks(solve_starts_at, feasibility))
        arrivals.append((final_at, (FINAL, None)))
        expected = _expected(reason="no_valid_route_found", reproducible=True)
        return limits, solve_starts_at, model, arrivals, final_at, {**expected, "ended_at_s": final_at}
    applies = optimisation if kind == "time_limit" else feasibility
    earliest = arrivals[-1][0] if kind == "time_limit" else float(feasibility)  # a timeout has none in time
    for _ in range(draw(st.integers(0, 3))):  # more incumbents, some before the limit that applies, some after
        at, message, _ = incumbent_at(earliest, applies + 30)
        arrivals.append((at, message))
    arrivals.sort(key=lambda arrival: arrival[0])
    read = [_incumbent(message, model) for at, message in arrivals if at < applies]
    hung = draw(st.booleans())
    ends_at = None if hung else applies + draw(st.integers(1, 100)) * TICK_S + 30
    if kind == "time_limit":
        expected = _expected(order=read[-1].order, ending="time_limit", reproducible=False, incumbents=tuple(read))
    else:
        expected = _expected(reason="timeout", reproducible=False)
    return limits, solve_starts_at, model, arrivals, ends_at, {**expected, "ended_at_s": float(applies)}


def _incumbent(message: Any, model: TourModel) -> Incumbent:
    _, tour, objective = message
    return Incumbent(order=_ids(model, tour), objective=objective)


@given(case=timelines())
def test_the_reading_ends_at_the_final_or_at_the_limit_that_applies_from_job_start(case: tuple[Any, ...]) -> None:
    limits, solve_starts_at, model, arrivals, ends_at, expected = case
    clock = FakeClock()
    job_started_s = clock.monotonic()
    clock.advance(solve_starts_at)
    pipe = TimelinePipe(
        clock,
        [(job_started_s + at, message) for at, message in arrivals],
        None if ends_at is None else job_started_s + ends_at,
    )
    streamed: list[Incumbent] = []

    before = {**_expected(), "ended_at_s": solve_starts_at}
    reading = read_tour_child(pipe, limits.from_start(clock, job_started_s), model, streamed.append)  # type: ignore[arg-type]
    exit_code = PARENT_ENDED_IT if reading.overran else 0
    outcome = tour_outcome(TourChildObservation(exit_code, reading.messages, reading.overran), model)
    after = {**_observe(outcome, tuple(streamed)), "ended_at_s": clock.monotonic() - job_started_s}

    assert_state_delta(
        before, after, TIMELINE_UNIVERSE, {slot: set_to(value) for slot, value in expected.items()}, strict=True
    )
