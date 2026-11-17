"""HealthService aggregation (ADR-011, brief §5/§7, D108): the start-up probe outcomes behind /healthz and /api/health.

Driving port: `HealthService(outcomes)` with the start-up probe outcomes. Probing each component exactly once, in
wiring order, is `StartupGate`'s behaviour (tests/unit/bootstrap/test_startup_gate.py).
Test Budget: 4 behaviors (liveness verdict, banners, component listing, registration-order independence) x 2 = 8;
2 property tests used.
"""

from __future__ import annotations

import itertools
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.probe import ProbeOutcome, ProbeResult
from tests.common.fakes import FakeClock
from tests.common.state_delta import assert_state_delta, set_to

UNHEALTHY: frozenset[ProbeOutcome] = frozenset({"degraded-unhealthy", "fatal"})
UNIVERSE = {
    "liveness.status",
    "liveness.reason",
    "detail.status",
    "detail.components",
    "detail.banners",
}


reasons = st.text(alphabet=st.characters(categories=("L", "N", "Zs")), min_size=1, max_size=40)
probe_results = st.one_of(
    st.builds(ProbeResult, outcome=st.sampled_from(["ok", "not_applicable"])),
    st.builds(
        ProbeResult, outcome=st.sampled_from(["degraded-healthy", "degraded-unhealthy", "fatal"]), reason=reasons
    ),
)
component_results = st.dictionaries(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12), probe_results, max_size=8
)


def _observe(service: HealthService | None) -> dict[str, Any]:
    if service is None:
        return dict.fromkeys(UNIVERSE)
    liveness, detail = service.liveness(), service.detail()
    return {
        "liveness.status": liveness.status,
        "liveness.reason": liveness.reason,
        "detail.status": detail.status,
        "detail.components": dict(detail.components),
        "detail.banners": list(detail.banners),
    }


@given(results=component_results)
def test_every_component_is_reported_and_any_unhealthy_outcome_makes_the_planner_unhealthy(
    results: dict[str, ProbeResult],
) -> None:
    unhealthy = sorted(name for name, result in results.items() if result.outcome in UNHEALTHY)
    status = "unhealthy" if unhealthy else "ok"

    before = _observe(None)
    after = _observe(HealthService(results))

    assert_state_delta(
        before,
        after,
        UNIVERSE,
        {
            "liveness.status": set_to(status),
            "liveness.reason": set_to(results[unhealthy[0]].reason if unhealthy else None),
            "detail.status": set_to(status),
            "detail.components": set_to(results),
            "detail.banners": set_to(
                [results[name].reason for name in sorted(results) if results[name].outcome == "degraded-unhealthy"]
            ),
        },
        strict=True,
    )


@given(results=component_results, data=st.data())
def test_health_is_independent_of_registration_order(results: dict[str, ProbeResult], data: st.DataObject) -> None:
    order = data.draw(st.permutations(list(results)))
    reordered = {name: results[name] for name in order}

    first = _observe(HealthService(results))
    second = _observe(HealthService(reordered))

    assert_state_delta(first, second, UNIVERSE, {}, strict=True)


STALE_AFTER_S = 60.0


class _Engine:
    """A component that can be probed again: it answers a new result each time and notes when it was asked."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.asked_at: list[float] = []

    def probe(self) -> ProbeResult:
        self.asked_at.append(self._clock.monotonic())
        return ProbeResult("degraded-healthy", f"answer {len(self.asked_at)}")


@given(gaps=st.lists(st.floats(min_value=0.0, max_value=200.0), max_size=25))
def test_reads_keep_the_probed_result_at_most_60_seconds_old_and_probe_at_most_once_per_60_seconds(
    gaps: list[float],
) -> None:
    clock = FakeClock()
    engine = _Engine(clock)
    health = HealthService(
        {"routing_provider": ProbeResult("ok"), "tour_solver": ProbeResult("ok")},
        clock=clock,
        reprobed={"routing_provider": engine},
    )
    started = clock.monotonic()
    for gap in gaps:
        clock.advance(gap)
        shown = health.detail().components
        last_probe = engine.asked_at[-1] if engine.asked_at else started
        assert clock.monotonic() - last_probe <= STALE_AFTER_S, "a result older than 60 s was shown"
        assert shown["routing_provider"] == (
            ProbeResult("degraded-healthy", f"answer {len(engine.asked_at)}") if engine.asked_at else ProbeResult("ok")
        )
        assert shown["tour_solver"] == ProbeResult("ok"), "another component was probed again"
    times = [started, *engine.asked_at]
    assert all(later - earlier > STALE_AFTER_S for earlier, later in itertools.pairwise(times)), (
        f"probed twice within 60 s by reads alone: {engine.asked_at}"
    )


@given(gap=st.floats(min_value=0.0, max_value=200.0))
def test_a_probe_on_demand_stores_its_result_with_its_time(gap: float) -> None:
    clock = FakeClock()
    engine = _Engine(clock)
    health = HealthService({"routing_provider": ProbeResult("ok")}, clock=clock, reprobed={"routing_provider": engine})
    clock.advance(gap)

    answered = health.probe("routing_provider")
    clock.advance(STALE_AFTER_S / 2)  # not older than 60 s: reading does not probe again
    shown = health.detail().components["routing_provider"]

    assert (answered, shown, len(engine.asked_at)) == (ProbeResult("degraded-healthy", "answer 1"),) * 2 + (1,)
