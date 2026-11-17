"""Step definitions of slice 06a (planning on the real road network): what the routing port gives the planner.

The offline road map stands in for the routing engine (atdd-infrastructure-policy.md: fakes only for external ports).
A place that no road open to vehicles reaches is scripted as `off_network: [[lat, lon]]` in the `MOCK_PLAN` file,
which the planner reads when it starts: the script is written before the first plan run, so the legs of plan run #4
stay cached when the place is added, and the Recalculate that follows asks only about the pairs of that place.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from pytest_bdd import given, parsers, then, when

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider, read_road_map
from overland_planner.bootstrap.startup import StartupRefusedError
from overland_planner.domain.catalog.coordinate import Coordinate
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import (
    add_poi,
    create_project,
    require_success,
    set_anchors,
)
from tests.acceptance.overland_route_planner_mvp.steps.direction_steps import plan_run_detail, runs_by_number
from tests.acceptance.overland_route_planner_mvp.steps.performance_steps import (
    PERF_REPORT_KEY,
    PI_PLAN_DEADLINE_S,
    PI_URL_KEY,
    finish,
    gpx_track,
    press,
)
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
from tests.acceptance.overland_route_planner_mvp.steps.planner import RemotePlanner
from tests.acceptance.overland_route_planner_mvp.steps.world import CATALOG_UNIVERSE, PLANNING_UNIVERSE, PlannerWorld
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, unchanged
from tests.contract.routing_port.recordings import recording

FAR_PLACE = "Bivacco fuori strada"
FAR_PLACE_AT = (44.6, 6.9)  # more than 250 m from any road open to vehicles: the script says so
RUNS_BEFORE = 4
ROAD_MAP_FILE = "off-network-road-map.yaml"
UNREACHABLE_REASON = "routing_engine_unreachable"
NOT_READY_REASON = "routing_engine_not_ready"
SYNTHETIC_KM_PER_H = 50.0
DEMO_PREFIX = "__demo"  # the live scenarios' own projects: the household's projects are never read or written
RECORDED_TORINO_SUSA = Path(__file__).parents[4] / "tests/contract/fixtures/valhalla-3.9.1/torino_susa_fossgis.json"
TORINO = ("Torino", 45.0703, 7.6869)
SUSA = ("Susa", 45.1370, 7.0500)
TRAIL_ENTRY = (44.55188, 7.11662)  # on the Strada dei Cannoni (OSM way 38239300), legally snapped within 21 m
E2E_LIMIT_S = 180
OBJECTIVES = {"minimise road distance": "distance", "minimise road time": "time"}


class SyntheticValhalla:
    """The routing engine's HTTP answers behind the planner's transport seam (synthetic: not recorded from a real
    engine). `/status` is the recorded 3.9.1 status; every matrix cell is the straight line x 1.3 at 50 km/h, from the
    places the question carries. `mode` is what the scenario does to the engine: healthy, down (connections are
    refused), newer (reports another version) or loading (answers /status, and 503 on the matrix: no map data yet)."""

    def __init__(self) -> None:
        self.mode = "healthy"
        self.reported_version = "3.9.1"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "down":
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/status":
            status = dict(recording("status")["response"])
            status["version"] = self.reported_version if self.mode == "newer" else status["version"]
            return httpx.Response(200, json=status)
        if self.mode == "loading":
            return httpx.Response(503, json={"error": "tiles are still loading"})
        body = json.loads(request.content)
        return httpx.Response(200, json={"sources_to_targets": self._rows(body["sources"], body["targets"])})

    @staticmethod
    def _rows(sources: list[dict[str, float]], targets: list[dict[str, float]]) -> list[list[dict[str, Any]]]:
        rows = []
        for a, source in enumerate(sources):
            row = []
            for b, target in enumerate(targets):
                metres = max(
                    1,
                    round(
                        1.3
                        * Coordinate(source["lat"], source["lon"]).great_circle_distance_m(
                            Coordinate(target["lat"], target["lon"])
                        )
                    ),
                )
                seconds = max(1, round(metres / (SYNTHETIC_KM_PER_H / 3.6)))
                row.append({"from_index": a, "to_index": b, "time": seconds, "distance": metres / 1000})
            rows.append(row)
        return rows


def route_on_synthetic_valhalla(world: PlannerWorld) -> SyntheticValhalla:
    """The planner routes with the real Valhalla adapter, against the synthetic engine, from its next start."""
    engine = SyntheticValhalla()
    world.environ["ROUTING_PROVIDER"] = "valhalla"
    world.routing_transport = httpx.MockTransport(engine)
    world.scratch["engine"] = engine
    return engine


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
    if "engine" not in world.scratch:  # on the real adapter there is no road map script to write
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


@given("the routing engine on the Pi cannot be reached")
def given_the_engine_cannot_be_reached(world: PlannerWorld) -> None:
    world.scratch["engine"].mode = "down"


@given("Valhalla has started but is not ready")
def given_valhalla_has_started_but_is_not_ready(world: PlannerWorld) -> None:
    world.scratch["engine"].mode = "loading"


@given(
    parsers.re(
        r'the routing engine on the Pi reports version "(?P<found>[^"]+)" '
        r'while the planner expects "(?P<expected>[^"]+)"'
    )
)
def given_the_engine_reports_another_version(world: PlannerWorld, found: str, expected: str) -> None:
    assert world.environ.get("VALHALLA_EXPECTED_VERSION", "3.9.1") == expected, "the planner expects another version"
    engine = world.scratch["engine"]
    engine.mode, engine.reported_version = "newer", found
    world.scratch["engine_versions"] = (found, expected)


@when(parsers.re(r"(?:Marco|he) presses Recalculate"))
def when_marco_presses_recalculate(world: PlannerWorld) -> None:
    world.scratch.pop("job_id", None)
    press_calculate(world)
    if "job_id" in world.scratch:  # a refused press starts no job
        world.scratch["first_recalculation"] = wait_until_job_ends(world)


@then("the health detail names the unexpected routing engine version")
def then_the_health_detail_names_both_versions(world: PlannerWorld) -> None:
    found, expected = world.scratch["engine_versions"]
    detail = world.marco().health_detail().json()["components"]["routing_provider"]
    assert (detail["outcome"], found in detail["reason"], expected in detail["reason"]) == (
        "degraded-healthy",
        True,
        True,
    ), detail


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


@then("the refusal is counted in the diagnostics as a refusal for an engine that was not ready")
def then_the_refusal_is_counted_as_an_engine_not_ready(world: PlannerWorld) -> None:
    assert world.response is not None, "Marco pressed nothing"
    refused_as = (world.response.status_code, world.response.json().get("code"))
    assert refused_as == (503, NOT_READY_REASON), f"the press was refused as {refused_as}"
    g4 = world.marco().diagnostics().json()["g4"]
    assert g4 == {"engine_refusals_30d": 1}, f"the diagnostics count the refusals for the engine as {g4}"


@then("plan run #4 and all items are unchanged")
def then_run_4_and_the_items_are_unchanged(world: PlannerWorld) -> None:
    if world.response is not None and world.response.status_code == 503:  # refused: not even a new run
        assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {}, strict=True)
        assert plan_run_detail(world, RUNS_BEFORE) == world.scratch["run_4"], "plan run #4 changed"
        assert sorted(runs_by_number(world)) == list(range(1, RUNS_BEFORE + 1)), "plan runs are not #1 to #4"
        return
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


@given(parsers.re(r'project "(?P<project>[^"]+)" uses the objective "(?P<label>[^"]+)"'))
def given_project_uses_the_objective(world: PlannerWorld, project: str, label: str) -> None:
    """The reference project with plan run #4, minimised on the project's objective (distance until Marco says so)."""
    given_plan_run_4_has_been_computed(world, project)
    assert world.project_id is not None, "no project is open"
    shown = world.marco().project(world.project_id).json().get("objective")
    assert shown == OBJECTIVES[label], f"the project minimises {shown!r}, not {OBJECTIVES[label]!r}"
    world.scratch["objective_before"] = shown


@given(parsers.re(r'Marco has selected "(?P<label>[^"]+)"'))
def given_marco_has_selected_the_objective(world: PlannerWorld, label: str) -> None:
    assert world.project_id is not None, "no project is open"
    world.note(world.marco().update_project(world.project_id, objective=OBJECTIVES[label]))
    require_success(world, f"select {label!r}")


@given("the planner is running with its default settings")
def given_the_planner_runs_with_its_default_settings(world: PlannerWorld) -> None:
    world.ensure_planner()


@then(parsers.re(r'the results state the objective "(?P<label>[^"]+)"'))
def then_the_results_state_the_objective(world: PlannerWorld, label: str) -> None:
    job = world.scratch["first_recalculation"]
    assert job["state"] == "done" and job["plan_run_id"], f"the Recalculate gave no new run: {job}"
    detail = plan_run_detail(world, RUNS_BEFORE + 1)
    stated = (detail.get("objective"), detail.get("objective_label"))
    assert stated == (OBJECTIVES[label], label), f"the new plan run states {stated}"
    assert plan_run_detail(world, RUNS_BEFORE).get("objective_label") == "minimise road distance", "run #4 changed"


@then("no new road legs were requested")
def then_no_new_road_legs_were_requested(world: PlannerWorld) -> None:
    job = world.scratch["first_recalculation"]
    assert job["legs_new"] == 0, f"the switch asked the routing engine for {job['legs_new']} legs: {job}"
    assert job["legs_cached"] == job["legs_total"] > 0, f"the legs were not all kept: {job}"


@then(parsers.re(r'its objective is "(?P<label>[^"]+)"'))
def then_its_objective_is(world: PlannerWorld, label: str) -> None:
    assert world.project_id is not None, "no project was created"
    opened = world.marco().project(world.project_id)
    assert opened.status_code == 200 and opened.json().get("objective") == OBJECTIVES[label], opened.text[:300]


# ------------------------------------------------------------------------------------------ secrets (NFR-4)
@given("the shared household password is set in Marco's settings")
def given_the_household_password_is_set(world: PlannerWorld) -> None:
    password = "household-" + secrets.token_hex(8)
    world.environ.update({"PLANNER_BASIC_AUTH_USER": "ferri", "PLANNER_BASIC_AUTH_PASSWORD": password})
    world.marco_auth = ("ferri", password)
    world.scratch["password"] = password


@given(parsers.re(r'plan run #4 of "(?P<project>[^"]+)" has been exported as GPX'))
def given_plan_run_4_has_been_exported(world: PlannerWorld, project: str) -> None:
    given_plan_run_4_has_been_computed(world, project)
    exported = world.marco().export_gpx(str(world.scratch["run_4"]["id"]))
    assert exported.status_code == 200 and exported.text.lstrip().startswith("<?xml"), exported.text[:200]
    world.scratch["gpx"] = exported.text


def _everything_the_results_say(world: PlannerWorld) -> str:
    """Every API answer about plan run #4 and the data the web page reads, as text. The home page itself is static
    (the built web page carries no run data) and is not served where the planner runs without a web build (CI job 7),
    so it is not one of the places."""
    marco, run = world.marco(), world.scratch["run_4"]
    assert world.project_id is not None, "no project is open"
    answers = [
        marco.plan_run(str(run["id"])),
        marco.plan_runs(world.project_id),
        marco.project(world.project_id),
        marco.projects(),
        marco.items(world.project_id),
        marco.health_detail(),
        marco.diagnostics(world.project_id),
    ]
    assert all(answer.status_code == 200 for answer in answers), [(a.url.path, a.status_code) for a in answers]
    return "\n".join(answer.text for answer in answers)


@when(parsers.re(r"Marco looks at (?P<place>the results of plan run #4|the planner log|the exported GPX file)"))
def when_marco_looks_at(world: PlannerWorld, place: str) -> None:
    seen = {
        "the results of plan run #4": lambda: _everything_the_results_say(world),
        "the planner log": lambda: world.scratch["capsys"].readouterr().out,
        "the exported GPX file": lambda: world.scratch["gpx"],
    }[place]()
    world.scratch["looked_at"] = (place, seen)


@then("the password does not appear there")
def then_the_password_does_not_appear(world: PlannerWorld) -> None:
    place, seen = world.scratch["looked_at"]
    assert world.scratch["run_4"]["id"] in seen or place == "the exported GPX file", f"{place}: nothing to look at"
    assert seen.strip(), f"{place} is empty"
    assert world.scratch["password"] not in seen, f"the password appears in {place}"


# ============================ live scenarios: the engine on the Pi (make acceptance-pi)
def demo_project(world: PlannerWorld, label: str) -> None:
    """A project of the live scenarios' own, `__demo <label> <time>`, with Torino as Start and Susa as End."""
    create_project(world, f"{DEMO_PREFIX} {label} {time.strftime('%Y%m%d-%H%M%S')}")
    require_success(world, "create the demo project")
    for name, lat, lon in (TORINO, SUSA):
        add_poi(world, name, lat, lon)
        require_success(world, f"add {name!r}")
    set_anchors(world, TORINO[0], SUSA[0])
    require_success(world, "set the Start and End")


def ended_plan_run(world: PlannerWorld) -> dict[str, Any]:
    job = world.scratch["job"]
    assert job["state"] == "done" and job["plan_run_id"], f"the Recalculate gave no plan run: {job}"
    answer = world.marco().plan_run(str(job["plan_run_id"]))
    assert answer.status_code == 200, f"the plan run did not open: {answer.status_code} {answer.text[:300]}"
    return dict(answer.json())


@given("the planner routes on Valhalla on Marco's Pi")
def given_the_planner_routes_on_valhalla_on_the_pi(world: PlannerWorld) -> None:
    url = os.environ.get(PI_URL_KEY)
    assert url, f"{PI_URL_KEY} is not set: this scenario runs only through make acceptance-pi (D96)"
    world.planner = RemotePlanner(url)
    world.planner.start()


@when(parsers.re(r'Marco presses Recalculate on "(?P<project>[^"]+)"'))
def when_marco_presses_recalculate_on_his_project(world: PlannerWorld, project: str) -> None:
    demo_project(world, project)
    press(world)
    finish(world, PI_PLAN_DEADLINE_S)
    world.scratch["run"] = ended_plan_run(world)


@then(
    parsers.re(
        r'the results show "(?P<provider>[^"]+)" with the date of its map data '
        r'and the routing profile "(?P<profile>[^"]+)"'
    )
)
def then_the_results_show_the_provider_date_and_profile(world: PlannerWorld, provider: str, profile: str) -> None:
    header = world.scratch["run"]["provider_header"]
    assert re.fullmatch(rf"{re.escape(provider)} \(map data \d{{4}}-\d{{2}}-\d{{2}}\) / profile: {profile}", header), (
        header
    )


@then(
    "the Torino to Susa leg is within 15% of the value shown by the openstreetmap.org route planner "
    "using its Valhalla engine"
)
def then_the_torino_to_susa_leg_is_close_to_openstreetmap_org(world: PlannerWorld) -> None:
    recorded_km = json.loads(RECORDED_TORINO_SUSA.read_text())["trip"]["legs"][0]["summary"]["length"]
    stops = {stop["name"]: stop for stop in world.scratch["run"]["stops"]}
    leg_km = stops[SUSA[0]]["leg_km"]
    assert leg_km is not None and abs(leg_km - recorded_km) <= 0.15 * recorded_km, (
        f"Torino to Susa is {leg_km} km, openstreetmap.org shows {recorded_km} km"
    )


@given(parsers.re(r'the entry of track "(?P<track>[^"]+)" lies on a forest track open to vehicles'))
def given_the_entry_of_a_track_lies_on_a_forest_track(world: PlannerWorld, track: str) -> None:
    demo_project(world, "trail entry")
    assert world.project_id is not None, "no project is open"
    lat, lon = TRAIL_ENTRY
    points = tuple((lat + step * 0.0003, lon, 1900.0 + step) for step in range(3))  # about 70 m from the entry
    world.note(world.marco().import_track_files(world.project_id, [(f"{track}.gpx", gpx_track(track, points))]))
    require_success(world, f"import the track {track!r}")


@then(parsers.re(r'the leg to "(?P<track>[^"]+)" is Confirmed'))
def then_the_leg_to_the_track_is_confirmed(world: PlannerWorld, track: str) -> None:
    detail = world.marco().plan_run(world.scratch["plan_run_id"]).json()
    stop = next((s for s in detail["stops"] if s["name"] == track and s["type"] == "track"), None)
    assert stop is not None, f"the plan has no stop for {track!r}: {[s['name'] for s in detail['stops']]}"
    assert stop["leg_confidence"] == "confirmed", f"the leg to {track!r} is {stop['leg_confidence']!r}: {stop}"


def e2e_report(world: PlannerWorld) -> dict[str, Any]:
    """The report of make perf-pi MODE=e2e that PERF_REPORT names: its 10 cold runs are the measurement."""
    path = os.environ.get(PERF_REPORT_KEY)
    assert path, (
        f"{PERF_REPORT_KEY} is not set: run make perf-pi MODE=e2e and name its report file in {PERF_REPORT_KEY}"
    )
    report: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    assert report.get("mode") == "e2e", f"{path} is not the report of make perf-pi MODE=e2e"
    return report


@given("the project of 60 items plus Start and End has no road legs known yet")
def given_the_project_has_no_road_legs_known_yet(world: PlannerWorld) -> None:
    report = e2e_report(world)
    assert report["items"] == 60, f"the report measured {report['items']} items"
    assert all(run.get("legs_cached") == 0 for run in report["runs"]), "a run started with road legs already known"


@when("Marco presses Recalculate 10 times, the known legs being forgotten before each run")
def when_marco_presses_recalculate_10_times_cold(world: PlannerWorld) -> None:
    report = e2e_report(world)
    assert (report["n"], len(report["runs"])) == (10, 10), f"the report holds {len(report['runs'])} of 10 runs"
    world.scratch["e2e"] = report


@then(
    parsers.re(
        r"the slowest of the 10 runs took at most (?P<seconds>\d+) seconds "
        r"from pressing Recalculate to the route on screen"
    ),
    converters={"seconds": int},
)
def then_the_slowest_run_is_within(world: PlannerWorld, seconds: int) -> None:
    runs = world.scratch["e2e"]["runs"]
    assert [run["state"] for run in runs] == ["done"] * 10, f"not every run finished: {[r['state'] for r in runs]}"
    slowest = max(run["e2e_s"] for run in runs)
    assert slowest <= seconds, f"the slowest of the 10 runs took {slowest} s: {[r['e2e_s'] for r in runs]}"


@then("every run counts, including retried ones, which are also shown separately")
def then_every_run_counts_and_retried_ones_are_shown(world: PlannerWorld) -> None:
    report = world.scratch["e2e"]
    assert len(report["runs"]) == report["n"] == 10, "a run is missing from the report"
    assert report["retried_runs"] == sum(1 for run in report["runs"] if run.get("retried")), "retried runs differ"
