"""Slice 12 steps at the HTTP API (US-21, ADR-007, D267, D268): whether a plan run's roads are an estimate.

`GET /api/plan-runs/{id}` gains `estimate: bool` (true when the run's road legs came from the offline road map, the
provider id `mock:...`); `GET /api/plan-runs/{id}/export.gpx` names the file `<project>-run<N>-estimate.gpx` and the
trip `Plan run #N (estimate)` for such a run, and keeps `<project>-run<N>.gpx` and `Plan run #N` for a Valhalla run.
The `@ui` scenarios of the feature are checked in tests/e2e/ui-foundation.spec.ts, not here.

No production module is imported: every step goes through the driving port, so until DELIVER adds the flag and the
names the Thens fail on what the planner answers (a business reason), not on an import. Opening a run and exporting
it change nothing Marco can see (Mandate 8: the planning universe stays as it was).
"""

from __future__ import annotations

from typing import Any

import defusedxml.ElementTree as SafeXml
from pytest_bdd import given, parsers, then, when

from tests.acceptance.overland_route_planner_mvp.steps.direction_steps import plan_run_detail
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import (
    FIRST_TRIP,
    GPX_NS,
    calculate_a_plan,
    export_the_plan,
    exported_file,
)
from tests.acceptance.overland_route_planner_mvp.steps.routing_steps import (
    given_plan_run_4_has_been_computed,
    route_on_synthetic_valhalla,
)
from tests.acceptance.overland_route_planner_mvp.steps.world import PLANNING_UNIVERSE, PlannerWorld
from tests.common.state_delta import assert_state_delta

OFFLINE_ROAD_MAP_WORDS = "offline estimate"  # provider_header of a `mock:` run (provider_label.py)
VALHALLA_WORDS = "Valhalla"  # provider_header of a `valhalla:` run
RUN_6 = 6


def _choose_run(world: PlannerWorld, number: int) -> dict[str, Any]:
    detail = plan_run_detail(world, number)
    world.scratch["plan_run_id"] = str(detail["id"])
    return detail


def _require_road_map(detail: dict[str, Any], words: str) -> None:
    """A precondition read at the port: the run names the road map it was planned on (slice 06a, D250)."""
    header = str(detail.get("provider_header", ""))
    assert words in header, f"plan run #{detail.get('number')} was not planned on that road map: {header!r}"


def _open_run(world: PlannerWorld, number: int) -> None:
    world.before = world.planning_view()
    world.scratch["opened_run"] = _choose_run(world, number)
    world.after = world.planning_view()
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {})


def _estimate_flag(world: PlannerWorld, number: int) -> object:
    detail = world.scratch.get("opened_run")
    assert detail is not None and detail.get("number") == number, f"plan run #{number} was not opened"
    assert "estimate" in detail, (
        f"plan run #{number} does not say whether its road legs are an estimate (it shows {sorted(detail)})"
    )
    return detail["estimate"]


# ---------------------------------------------------------------------------------------------------- Given
@given(parsers.re(r'plan run #4 of "(?P<project>[^"]+)" took its road legs from the offline road map'))
def given_plan_run_4_on_the_offline_road_map(world: PlannerWorld, project: str) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} is set up here"
    assert "engine" not in world.scratch, "this world routes on Valhalla, not on the offline road map"
    given_plan_run_4_has_been_computed(world, project)
    _require_road_map(_choose_run(world, 4), OFFLINE_ROAD_MAP_WORDS)


@given(parsers.re(r'plan run #6 of "(?P<project>[^"]+)" took its road legs from Valhalla'))
def given_plan_run_6_on_valhalla(world: PlannerWorld, project: str) -> None:
    """The real Valhalla adapter against the synthetic engine (slice 06a); runs #5 and #6 are two more presses."""
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} is set up here"
    if "engine" not in world.scratch:
        route_on_synthetic_valhalla(world)
    given_plan_run_4_has_been_computed(world, project)
    for _ in range(RUN_6 - 4):
        calculate_a_plan(world)
    _require_road_map(_choose_run(world, RUN_6), VALHALLA_WORDS)


# ----------------------------------------------------------------------------------------------------- When
@when(parsers.re(r"Marco opens plan run #(?P<number>\d+)$"), converters={"number": int})
def when_marco_opens_plan_run(world: PlannerWorld, number: int) -> None:
    _open_run(world, number)


@when("Marco downloads its GPX")
def when_marco_downloads_its_gpx(world: PlannerWorld) -> None:
    export_the_plan(world)  # the run chosen by the Given; `he downloads` checks nothing changed


@when(parsers.re(r"Marco opens plan run #(?P<number>\d+) and downloads its GPX"), converters={"number": int})
def when_marco_opens_plan_run_and_downloads_its_gpx(world: PlannerWorld, number: int) -> None:
    _open_run(world, number)
    export_the_plan(world)


# ----------------------------------------------------------------------------------------------------- Then
@then(parsers.re(r"plan run #(?P<number>\d+) is reported as an estimate"), converters={"number": int})
def then_plan_run_is_reported_as_an_estimate(world: PlannerWorld, number: int) -> None:
    flag = _estimate_flag(world, number)
    assert flag is True, f"plan run #{number} took its road legs from the offline road map but says estimate={flag!r}"


@then(parsers.re(r"plan run #(?P<number>\d+) is not reported as an estimate"), converters={"number": int})
def then_plan_run_is_not_reported_as_an_estimate(world: PlannerWorld, number: int) -> None:
    flag = _estimate_flag(world, number)
    assert flag is False, f"plan run #{number} took its road legs from Valhalla but says estimate={flag!r}"


@then(parsers.re(r'the trip name inside the file is "(?P<name>[^"]+)"'))
def then_the_trip_name_inside_the_file_is(world: PlannerWorld, name: str) -> None:
    root = SafeXml.fromstring(exported_file(world))
    stated = root.findtext(f"{{{GPX_NS}}}metadata/{{{GPX_NS}}}name")
    assert stated == name, f"the file calls the trip {stated!r}, not {name!r}"
