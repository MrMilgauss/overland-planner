"""Step definitions of slice 06a (planning on the real road network): what the routing port gives the planner.

The offline road map stands in for the routing engine (atdd-infrastructure-policy.md: fakes only for external ports).
A place that no road open to vehicles reaches is scripted as `off_network: [[lat, lon]]` in the `MOCK_PLAN` file,
which the planner reads when it starts: the script is written before the first plan run, so the legs of plan run #4
stay cached when the place is added, and the Recalculate that follows asks only about the pairs of that place.
"""

from __future__ import annotations

from typing import Any

import yaml
from pytest_bdd import given, parsers, then, when

from overland_planner.bootstrap.startup import StartupRefusedError
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import add_poi, require_success
from tests.acceptance.overland_route_planner_mvp.steps.direction_steps import plan_run_detail, runs_by_number
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import (
    FIRST_TRIP,
    _plan_job,
    calculate_a_plan,
    prepare_day_trip,
    press_calculate,
    wait_for_plan,
)
from tests.acceptance.overland_route_planner_mvp.steps.world import CATALOG_UNIVERSE, PLANNING_UNIVERSE, PlannerWorld
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, unchanged

FAR_PLACE = "Bivacco fuori strada"
FAR_PLACE_AT = (44.6, 6.9)  # more than 250 m from any road open to vehicles: the script says so
RUNS_BEFORE = 4


def script_off_network_places(world: PlannerWorld, *places: tuple[float, float]) -> None:
    """The offline road map answers every pair from or to these points as off the network; read at start-up."""
    path = world.tmp_path / "off-network-road-map.yaml"
    document = {"detour_factor": 1.3, "pairs": [], "off_network": [list(place) for place in places]}
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    world.environ["MOCK_PLAN"] = str(path)


def recalculated_job(world: PlannerWorld) -> dict[str, Any]:
    """The job of the Recalculate just pressed, once it ended."""
    return _plan_job(world, world.scratch["job_id"])


@given(parsers.re(r'plan run #4 of "(?P<project>[^"]+)" has been computed'))
def given_plan_run_4_has_been_computed(world: PlannerWorld, project: str) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} has a day trip to plan here"
    script_off_network_places(world, FAR_PLACE_AT)
    try:
        prepare_day_trip(world)
    except StartupRefusedError as refused:
        raise AssertionError(
            f"the planner refused to start with the scripted road map ({refused!r}): the offline road map does not "
            "read the `off_network` key that slice 06a scripts"
        ) from None
    for _ in range(RUNS_BEFORE):
        calculate_a_plan(world)
    world.scratch["run_4"] = plan_run_detail(world, RUNS_BEFORE)


@given(
    parsers.re(r'Marco has added POI "(?P<poi>[^"]+)" more than 250 m from any road open to vehicles'),
)
def given_marco_added_a_poi_far_from_any_road(world: PlannerWorld, poi: str) -> None:
    assert poi == FAR_PLACE, f"only {FAR_PLACE!r} is scripted off the network"
    add_poi(world, poi, *FAR_PLACE_AT)
    require_success(world, f"add {poi!r}")


@when("Marco presses Recalculate")
def when_marco_presses_recalculate(world: PlannerWorld) -> None:
    press_calculate(world)
    wait_for_plan(world)
    world.scratch["first_recalculation"] = recalculated_job(world)


@then(parsers.re(r'the new plan run fails and names "(?P<poi>[^"]+)" as unreachable'))
def then_the_new_run_fails_and_names_the_place(world: PlannerWorld, poi: str) -> None:
    assert_state_delta(
        world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((RUNS_BEFORE + 1, "failed"))}
    )
    detail = plan_run_detail(world, RUNS_BEFORE + 1)
    assert detail.get("failure_reason") == "unreachable", f"the run fails with {detail.get('failure_reason')!r}"
    report = detail.get("report") or {}
    texts = [*world.seen_messages, str(report.get("reason") or ""), *(detail.get("messages") or ())]
    assert any(poi in text for text in texts), f"nothing Marco read names {poi!r}: {texts}"


@then("plan run #4 and all items are unchanged")
def then_run_4_and_the_items_are_unchanged(world: PlannerWorld) -> None:
    assert_state_delta(
        world.before,
        world.after,
        CATALOG_UNIVERSE,
        {"project.items": unchanged(), "projects.names": unchanged()},
    )
    assert plan_run_detail(world, RUNS_BEFORE) == world.scratch["run_4"], "plan run #4 changed"
    assert sorted(runs_by_number(world)) == list(range(1, RUNS_BEFORE + 2)), "plan runs are not #1 to #5"


@then(parsers.re(r'the next Recalculate asks the routing engine about "(?P<poi>[^"]+)" again'))
def then_the_next_recalculate_asks_again(world: PlannerWorld, poi: str) -> None:
    first = world.scratch["first_recalculation"]
    press_calculate(world)
    wait_for_plan(world)
    second = recalculated_job(world)
    assert first["legs_new"] > 0, f"the first Recalculate asked nothing about {poi!r}: {first}"
    assert first["legs_cached"] > 0, f"the first Recalculate kept no road leg from plan run #4: {first}"
    for job in (first, second):
        assert job["legs_new"] + job["legs_cached"] == job["legs_total"], f"legs do not add up: {job}"
    assert (second["legs_new"], second["legs_cached"]) == (first["legs_new"], first["legs_cached"]), (
        f"{poi!r} was not asked again, the other legs cached: first {first}, second {second}"
    )
