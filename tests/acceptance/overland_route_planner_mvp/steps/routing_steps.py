"""Step definitions of slice 06a (planning on the real road network): what the routing port gives the planner.

The offline road map stands in for the routing engine (atdd-infrastructure-policy.md: fakes only for external ports).
A place that no road open to vehicles reaches is scripted as `off_network: [[lat, lon]]` in the `MOCK_PLAN` file,
which the planner reads when it starts: the script is written before the first plan run, so the legs of plan run #4
stay cached when the place is added, and the Recalculate that follows asks only about the pairs of that place.
"""

from __future__ import annotations

import time
from typing import Any

import yaml
from pytest_bdd import given, parsers, then, when

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider, read_road_map
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import add_poi, require_success
from tests.acceptance.overland_route_planner_mvp.steps.direction_steps import plan_run_detail, runs_by_number
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import (
    FIRST_TRIP,
    PLAN_DEADLINE_S,
    POLL_EVERY_S,
    TERMINAL_JOB_STATES,
    _plan_job,
    calculate_a_plan,
    ensure_item,
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
ROAD_MAP_FILE = "off-network-road-map.yaml"
UNREACHABLE_REASON = "routing_engine_unreachable"


def script_off_network_places(world: PlannerWorld, *places: tuple[float, float]) -> None:
    """The offline road map answers every pair from or to these points as off the network; read at start-up."""
    path = world.tmp_path / ROAD_MAP_FILE
    document = {"detour_factor": 1.3, "pairs": [], "off_network": [list(place) for place in places]}
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    world.environ["MOCK_PLAN"] = str(path)


def recalculated_job(world: PlannerWorld) -> dict[str, Any]:
    """The job of the Recalculate just pressed, once it ended."""
    return _plan_job(world, world.scratch["job_id"])


def wait_until_job_ends(world: PlannerWorld) -> dict[str, Any]:
    """Poll the job of the press like the browser does, until it ends in any state; its last poll."""
    job_id = world.scratch["job_id"]
    deadline = time.monotonic() + PLAN_DEADLINE_S
    job = _plan_job(world, job_id)
    while job["state"] not in TERMINAL_JOB_STATES:
        assert time.monotonic() < deadline, f"the plan was not over after {PLAN_DEADLINE_S:.0f} s: {job}"
        time.sleep(POLL_EVERY_S)
        job = _plan_job(world, job_id)
    world.after = world.planning_view()
    return job


def arm_faults(world: PlannerWorld, faults: dict[str, object] | None) -> None:
    """The road map under the planner starts failing as scripted from now on (`faults` as `MOCK_PLAN` writes them), or
    stops when `None`; pairs it answered before are not counted against it."""
    provider = world.routing_provider
    assert isinstance(provider, MockRoutingProvider), "the scenario did not give the planner a road map it can arm"
    path = world.tmp_path / "fault-plan.yaml"
    document: dict[str, object] = {"pairs": [], **({} if faults is None else {"faults": faults})}
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    provider.arm_faults(read_road_map(path).faults)


def other_included_items(world: PlannerWorld, *, besides: str) -> int:
    """`k`: the Included items that are not the Start or the End, without the one named `besides` (the new POI)."""
    return sum(1 for item in world.items() if item["included"] and not item.get("anchor") and item["name"] != besides)


@given(parsers.re(r'plan run #4 of "(?P<project>[^"]+)" has been computed'))
def given_plan_run_4_has_been_computed(world: PlannerWorld, project: str) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} has a day trip to plan here"
    script_off_network_places(world, *([] if "reference_places" in world.scratch else [FAR_PLACE_AT]))
    if "reference_places" in world.scratch:  # a world whose road map the scenario arms (slice 06a, D248)
        world.routing_provider = MockRoutingProvider(script=read_road_map(world.tmp_path / ROAD_MAP_FILE))
    try:
        prepare_day_trip(world)
    except StartupRefusedError as refused:
        raise AssertionError(
            f"the planner refused to start with the scripted road map ({refused!r}): the offline road map does not "
            "read the `off_network` key that slice 06a scripts"
        ) from None
    for place in world.scratch.get("reference_places", ()):
        ensure_item(world, place)
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


@given(
    parsers.re(r'Marco has added POI "(?P<poi>[^"]+)" at (?P<lat>[\d.]+), (?P<lon>[\d.]+)'),
    converters={"lat": float, "lon": float},
)
def given_marco_added_a_poi_at(world: PlannerWorld, poi: str, lat: float, lon: float) -> None:
    add_poi(world, poi, lat, lon)
    require_success(world, f"add {poi!r}")
    world.scratch["new_poi"] = poi


@given(parsers.re(r"the routing engine fails after answering (?P<legs>\d+) of the new legs"), converters={"legs": int})
def given_the_engine_fails_after_answering(world: PlannerWorld, legs: int) -> None:
    arm_faults(world, {"fail_after_pairs": legs, "kind": "unreachable"})
    world.scratch["legs_answered_before_failure"] = legs


@when("Marco presses Recalculate")
def when_marco_presses_recalculate(world: PlannerWorld) -> None:
    press_calculate(world)
    world.scratch["first_recalculation"] = wait_until_job_ends(world)


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


@then("the next Recalculate requests only the legs that were not answered")
def then_the_next_recalculate_requests_only_the_unanswered_legs(world: PlannerWorld) -> None:
    answered = world.scratch["legs_answered_before_failure"]
    failed = world.scratch["first_recalculation"]
    items = other_included_items(world, besides=world.scratch["new_poi"])
    new_legs = 2 * items + 2  # Start -> POI, each item -> POI, POI -> each item, POI -> End
    assert items >= answered, f"{items} items other than the anchors: fewer than the {answered} legs answered"
    assert (failed["state"], failed["reason"], failed["plan_run_id"]) == ("failed", UNREACHABLE_REASON, None), failed
    assert (failed["legs_new"], failed["stoppable"]) == (answered, False), f"legs answered before the failure: {failed}"
    assert_state_delta(
        world.before,
        world.after,
        PLANNING_UNIVERSE,
        {"project.plan_runs": unchanged(), "project.items": unchanged(), "projects.names": unchanged()},
    )
    arm_faults(world, None)
    press_calculate(world)
    wait_for_plan(world)
    next_job = recalculated_job(world)
    assert next_job["legs_new"] == new_legs - answered, f"the next Recalculate asked {next_job['legs_new']}: {next_job}"
    assert next_job["legs_cached"] >= answered + failed["legs_cached"], f"the legs answered were not kept: {next_job}"
    assert next_job["legs_new"] + next_job["legs_cached"] == next_job["legs_total"], f"legs do not add up: {next_job}"
    assert failed["legs_new"] + next_job["legs_new"] == new_legs, f"{failed['legs_new']} + {next_job['legs_new']}"
