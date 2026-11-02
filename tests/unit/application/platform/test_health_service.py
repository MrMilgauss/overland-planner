"""HealthService aggregation (ADR-011, brief §5/§7, D108): the start-up probe outcomes behind /healthz and /api/health.

Driving port: `HealthService.after_probing(components)`. Driven port: each component's `Probeable.probe()`.
Test Budget: 4 behaviors (liveness verdict, banners, component listing probed once, registration-order
independence) x 2 = 8; 2 property tests used.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.platform.facade import HealthService
from overland_planner.application.ports.probe import ProbeOutcome, ProbeResult
from tests.common.state_delta import assert_state_delta, set_to

UNHEALTHY: frozenset[ProbeOutcome] = frozenset({"degraded-unhealthy", "fatal"})
UNIVERSE = {
    "probe_calls",
    "liveness.status",
    "liveness.reason",
    "detail.status",
    "detail.components",
    "detail.banners",
}


class ScriptedComponent:
    """A driven-port double: answers its probe with a scripted result and counts the calls."""

    def __init__(self, result: ProbeResult) -> None:
        self.result = result
        self.calls = 0

    def probe(self) -> ProbeResult:
        self.calls += 1
        return self.result


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


def _observe(service: HealthService | None, components: Mapping[str, ScriptedComponent]) -> dict[str, Any]:
    calls = {name: component.calls for name, component in components.items()}
    if service is None:
        return dict.fromkeys(UNIVERSE) | {"probe_calls": calls}
    liveness, detail = service.liveness(), service.detail()
    return {
        "probe_calls": calls,
        "liveness.status": liveness.status,
        "liveness.reason": liveness.reason,
        "detail.status": detail.status,
        "detail.components": dict(detail.components),
        "detail.banners": list(detail.banners),
    }


@given(results=component_results)
def test_start_up_probes_every_component_once_and_any_unhealthy_outcome_makes_the_planner_unhealthy(
    results: dict[str, ProbeResult],
) -> None:
    components = {name: ScriptedComponent(result) for name, result in results.items()}
    unhealthy = sorted(name for name, result in results.items() if result.outcome in UNHEALTHY)
    status = "unhealthy" if unhealthy else "ok"

    before = _observe(None, components)
    service = HealthService.after_probing(components)
    after = _observe(service, components)

    assert_state_delta(
        before,
        after,
        UNIVERSE,
        {
            "probe_calls": set_to(dict.fromkeys(results, 1)),
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
    registered = {name: ScriptedComponent(results[name]) for name in results}
    reordered = {name: ScriptedComponent(results[name]) for name in order}

    first = _observe(HealthService.after_probing(registered), registered)
    second = _observe(HealthService.after_probing(reordered), reordered)

    assert_state_delta(first, second, UNIVERSE, {}, strict=True)
