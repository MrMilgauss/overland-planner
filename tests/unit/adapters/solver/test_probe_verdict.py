"""Solver probe verdict (ADR-011 Amendment 1, brief §6/§7): what the child's observations mean for the planner.

Driving port: `probe_verdict(observation)`, a pure function (its signature is the interface). The probe is ok iff the
child exited cleanly and both solves returned the known-optimal order at the known optimum; anything else is
degraded-unhealthy with reason optimizer_unavailable.
Test Budget: 1 behavior (verdict) x 2 = 2; 1 property test used. Expectations come from how each observation was
built (healthy by construction vs one injected fault), not from re-deriving the rule.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.adapters.solver.probe_instance import (
    KNOWN_OPTIMAL_ORDER,
    KNOWN_OPTIMUM,
    NODE_COUNT,
    ProbeObservation,
    probe_verdict,
)
from overland_planner.application.ports.probe import ProbeResult
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"verdict.outcome", "verdict.reason"}
OK = ProbeResult(outcome="ok")
OPTIMIZER_UNAVAILABLE = ProbeResult(outcome="degraded-unhealthy", reason="optimizer_unavailable")
OPTIMAL = (KNOWN_OPTIMAL_ORDER, KNOWN_OPTIMUM)

other_orders = st.permutations(list(range(1, NODE_COUNT))).map(tuple).filter(lambda o: o != KNOWN_OPTIMAL_ORDER)
other_objectives = st.integers(min_value=0, max_value=10_000).filter(lambda c: c != KNOWN_OPTIMUM)
wrong_solves = st.one_of(
    st.tuples(other_orders, st.just(KNOWN_OPTIMUM)),
    st.tuples(st.just(KNOWN_OPTIMAL_ORDER), other_objectives),
    st.tuples(other_orders, other_objectives),
)
failed_exits = st.one_of(st.none(), st.integers(min_value=-15, max_value=255).filter(lambda code: code != 0))


@st.composite
def faulty_observations(draw: st.DrawFn) -> ProbeObservation:
    """A healthy observation with exactly one kind of fault injected."""
    fault = draw(st.sampled_from(["exit", "first_solve", "second_solve", "missing_solves"]))
    if fault == "exit":
        return ProbeObservation(exit_code=draw(failed_exits), solves=(OPTIMAL, OPTIMAL))
    if fault == "first_solve":
        return ProbeObservation(exit_code=0, solves=(draw(wrong_solves), OPTIMAL))
    if fault == "second_solve":
        return ProbeObservation(exit_code=0, solves=(OPTIMAL, draw(wrong_solves)))
    return ProbeObservation(exit_code=draw(st.sampled_from([0, None])), solves=draw(st.sampled_from([(), (OPTIMAL,)])))


observations = st.one_of(
    st.just((ProbeObservation(exit_code=0, solves=(OPTIMAL, OPTIMAL)), OK)),
    faulty_observations().map(lambda observation: (observation, OPTIMIZER_UNAVAILABLE)),
)


def _observe(verdict: ProbeResult | None) -> dict[str, Any]:
    if verdict is None:
        return dict.fromkeys(UNIVERSE)
    return {"verdict.outcome": verdict.outcome, "verdict.reason": verdict.reason}


@given(case=observations)
def test_probe_is_ok_only_when_both_solves_return_the_known_optimum_from_a_clean_exit(
    case: tuple[ProbeObservation, ProbeResult],
) -> None:
    observation, expected = case

    before = _observe(None)
    after = _observe(probe_verdict(observation))

    assert_state_delta(
        before,
        after,
        UNIVERSE,
        {"verdict.outcome": set_to(expected.outcome), "verdict.reason": set_to(expected.reason)},
        strict=True,
    )
