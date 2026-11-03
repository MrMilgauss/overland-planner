"""Start-up gate (brief §7, D190): a fatal probe outcome refuses the start before anything else is probed.

Driving port: `StartupGate.probe_in_order(components)` / `StartupGate.refuse`. Driven ports: each component's
`Probeable.probe()` and the `EventLog` (the refusal line).
Test Budget: 2 behaviors (refuse at the first fatal component, serve when none is fatal) x 2 = 4; 1 property test.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.bootstrap.startup import REFUSAL_EXIT_CODE, StartupGate, StartupRefusedError
from tests.common.state_delta import assert_state_delta, set_to, unchanged

UNIVERSE = {"probed", "event_log", "exit_code", "health.components"}


class RecordingEventLog:
    """`EventLog` port double: keeps every event line."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **fields: object) -> None:
        self.lines.append((event, fields))

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


class ScriptedComponent:
    """A driven-port double: answers its probe with a scripted result and records that it was probed."""

    def __init__(self, name: str, result: ProbeResult, probed: list[str]) -> None:
        self._name, self._result, self._probed = name, result, probed

    def probe(self) -> ProbeResult:
        self._probed.append(self._name)
        return self._result


reasons = st.text(alphabet=st.characters(categories=("L", "N", "Zs", "Pd")), min_size=1, max_size=30)
probe_results = st.one_of(
    st.builds(ProbeResult, outcome=st.sampled_from(["ok", "not_applicable"])),
    st.builds(
        ProbeResult, outcome=st.sampled_from(["degraded-healthy", "degraded-unhealthy", "fatal"]), reason=reasons
    ),
)
wiring = st.lists(
    st.tuples(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12), probe_results),
    unique_by=lambda entry: entry[0],
    max_size=8,
)


@given(wired=wiring)
def test_start_up_refuses_iff_a_component_is_fatal_naming_the_first_and_probing_nothing_after_it(
    wired: list[tuple[str, ProbeResult]],
) -> None:
    probed: list[str] = []
    event_log = RecordingEventLog()
    components = {name: ScriptedComponent(name, result, probed) for name, result in wired}
    before: dict[str, Any] = {"probed": [], "event_log": [], "exit_code": None, "health.components": None}

    after = dict(before)
    try:
        health = StartupGate(event_log).probe_in_order(components)
        after["health.components"] = dict(health.detail().components)
    except StartupRefusedError as refused:
        after["exit_code"] = refused.code
    after.update(probed=list(probed), event_log=list(event_log.lines))

    names = [name for name, _ in wired]
    fatal = [index for index, (_, result) in enumerate(wired) if result.outcome == "fatal"]
    if fatal:
        first = fatal[0]
        name, result = wired[first]
        expected = {
            "probed": set_to(names[: first + 1]),
            "event_log": set_to([("health.startup.refused", {"component": name, "reason": result.reason})]),
            "exit_code": set_to(REFUSAL_EXIT_CODE),
            "health.components": unchanged(),
        }
    else:
        expected = {
            "probed": set_to(names),
            "event_log": unchanged(),
            "exit_code": unchanged(),
            "health.components": set_to(dict(wired)),
        }
    assert_state_delta(before, after, universe=UNIVERSE, expected=expected, strict=True)


@given(component=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12), reason=reasons)
def test_a_direct_refusal_logs_one_line_and_exits_non_zero(component: str, reason: str) -> None:
    # bypass: a refusal leaves no state to diff besides its one log line and exit code, both asserted exactly.
    event_log = RecordingEventLog()
    with pytest.raises(StartupRefusedError) as refused:
        StartupGate(event_log).refuse(component, reason)
    assert (refused.value.code, event_log.lines) == (
        REFUSAL_EXIT_CODE,
        [("health.startup.refused", {"component": component, "reason": reason})],
    )
    assert REFUSAL_EXIT_CODE != 0
