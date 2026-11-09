"""Planning steps: Calculate, the itinerary and the GPX export (US-02b, slice 01b).

Everything goes through the driving ports (D115): the plan endpoints, or a real browser for the `@ui` scenario. Every
press and export captures the universe before and after (Mandate 8), and the Thens assert outcomes (D186): the
itinerary as the planner shows it and the file as Marco downloads it. "Track X from A to B" is checked by coordinates
(D109). The plan run and itinerary JSON shape is DISTILL's proposal: it asks only for what the scenarios need.
Road legs follow the offline road map, straight line x 1.3 (brief §6). Givens reuse the helpers of the
catalog steps and of the Whens (Pillar 2).
"""

from __future__ import annotations

import itertools
import re
import time
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as SafeXml
import xmlschema
from pytest_bdd import given, parsers, then, when

from tests.acceptance.overland_route_planner_mvp.steps.browser import REPO_ROOT, BrowserRun, FirstPlanJourney
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import (
    add_poi,
    assert_track_from_to,
    create_project,
    import_trail_files,
    require_success,
    set_anchors,
)
from tests.acceptance.overland_route_planner_mvp.steps.places import (
    ENTRY_EXIT_TOLERANCE_M,
    FIXTURES,
    PLACES,
    TRAIL_FILES,
    distance_m,
    trail_file_bytes,
)
from tests.acceptance.overland_route_planner_mvp.steps.planner import ServerPlanner
from tests.acceptance.overland_route_planner_mvp.steps.world import PLANNING_UNIVERSE, PlannerWorld
from tests.common.predicates import gained
from tests.common.solver_fakes import HoldingTourSolver, UnavailableTourSolver
from tests.common.state_delta import assert_state_delta

FIRST_TRIP = "Alpi Occidentali giugno 2027"
ASSIETTA = "Strada dell'Assietta"
HOME = "Casa Marco, Torino"
BRIANCON = "Briancon"
GPX_SCHEMA = FIXTURES.parent / "schemas" / "gpx-1.1.xsd"
GPX_NS = "http://www.topografix.com/GPX/1/1"
SCHEMA_LOCATION_ATTRIBUTE = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"
ROAD_FACTOR = 1.3  # the offline road map: straight line x 1.3 (brief §6)
TERMINAL_JOB_STATES = {"done", "refused", "failed", "cancelled", "timed_out"}  # ADR-015 "Job states"
PLAN_DEADLINE_S = 120.0  # a cold first import of OR-Tools alone took over 10 s on the Mac
HOLD_DEADLINE_S = 30.0
POLL_EVERY_S = 0.05
TRACK_FILE_OF = {trail.track_name: trail.file_name for trail in TRAIL_FILES.values() if trail.track_name}


# ----------------------------------------------------------------------------------------------- helpers
def ensure_project(world: PlannerWorld, name: str) -> None:
    if world.project_id is None:
        create_project(world, name)
        require_success(world, f"create the project {name!r}")
    assert world.project_name == name, f"the open project is {world.project_name!r}, not {name!r}"


def ensure_item(world: PlannerWorld, name: str) -> None:
    """The trail or place named `name` is in the open project, Included (the state every new item starts in)."""
    if not any(item["name"] == name for item in world.items()):
        if name in TRACK_FILE_OF:
            import_trail_files(world, TRACK_FILE_OF[name])
        else:
            place = PLACES[name]
            add_poi(world, name, place.lat, place.lon)
        require_success(world, f"add {name!r}")
    assert world.item_named(name)["included"], f"{name!r} is not Included"


def prepare_day_trip(world: PlannerWorld) -> None:
    ensure_project(world, FIRST_TRIP)
    for name in (ASSIETTA, HOME, BRIANCON):
        ensure_item(world, name)
    set_anchors(world, HOME, HOME)
    require_success(world, "set home as Start and End")


def press_calculate(world: PlannerWorld) -> None:
    """Marco presses Calculate; the plan is not awaited. A refused press keeps the job it was refused for."""
    assert world.project_id is not None, "no project is open"
    world.before = world.planning_view()
    armed = _rule_breaking_optimizer_is_armed(world)
    answer = world.note(_calculate_ignoring_memo(world) if armed else world.marco().calculate(world.project_id))
    if answer.status_code == 202:
        world.scratch["job_id"] = str(answer.json()["job_id"])
        if armed:
            job = _plan_job(world, world.scratch["job_id"])
            assert job["ignore_memo"] is True, f"the armed Calculate did not ignore the memo: {job}"
    world.after = world.planning_view()


def _rule_breaking_optimizer_is_armed(world: PlannerWorld) -> bool:
    """The W1 Given keeps its first, real plan as `previous_success`, then arms the rule-breaking optimizer (D218)."""
    return "previous_success" in world.scratch


def _calculate_ignoring_memo(world: PlannerWorld) -> Any:
    """Calculate with `?ignore_memo=true` (D218), so the armed optimizer is really asked to propose an order rather than
    the memo answering from plan run #1. `PlannerSession.calculate` takes no parameters, so this press is made here."""
    return world.marco()._request("POST", f"/api/projects/{world.project_id}/plan-runs", params={"ignore_memo": "true"})


def wait_for_plan(world: PlannerWorld) -> None:
    """Poll the job like the browser does, until it ends with a plan run."""
    job_id = world.scratch.get("job_id")
    assert job_id is not None, f"no plan is being calculated: {_last_answer(world)}"
    deadline = time.monotonic() + PLAN_DEADLINE_S
    while True:
        job = _plan_job(world, job_id)
        if job["state"] in TERMINAL_JOB_STATES:
            break
        assert time.monotonic() < deadline, f"the plan was not ready after {PLAN_DEADLINE_S:.0f} s: {job}"
        time.sleep(POLL_EVERY_S)
    assert job["state"] == "done" and job["plan_run_id"], f"the plan ended without a plan run: {job}"
    world.scratch["plan_run_id"] = str(job["plan_run_id"])
    world.after = world.planning_view()


def calculate_a_plan(world: PlannerWorld) -> None:
    press_calculate(world)
    wait_for_plan(world)


def start_a_plan_that_keeps_working(world: PlannerWorld) -> None:
    solver = HoldingTourSolver()
    world.tour_solver = solver
    prepare_day_trip(world)
    press_calculate(world)
    assert world.response is not None and world.response.status_code == 202, f"Calculate: {_last_answer(world)}"
    assert solver.wait_until_asked(HOLD_DEADLINE_S), "the plan never reached the optimizer"
    job = _plan_job(world, world.scratch["job_id"])
    assert job["state"] not in TERMINAL_JOB_STATES, f"the plan is no longer being worked out: {job}"


def export_the_plan(world: PlannerWorld) -> None:
    world.before = world.planning_view()
    world.scratch["export"] = world.note(world.marco().export_gpx(_plan_run_id(world)))
    world.after = world.planning_view()


def journey(world: PlannerWorld) -> FirstPlanJourney | None:
    return world.scratch.get("browser_journey")


def assert_first_plan_was_added(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((1, "ready"))})


def assert_export_changed_nothing(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {})


def stops(world: PlannerWorld) -> list[dict[str, Any]]:
    answer = world.marco().plan_run(_plan_run_id(world))
    assert answer.status_code == 200, f"the plan run did not open: {answer.status_code} {answer.text[:300]}"
    return list(answer.json()["stops"])


def stop_named(world: PlannerWorld, name: str) -> dict[str, Any]:
    matches = [stop for stop in stops(world) if stop["name"] == name]
    assert len(matches) == 1, f"expected {name!r} once in the itinerary, found {len(matches)}"
    return matches[0]


def assert_driven_from_to(world: PlannerWorld, track_name: str, entry_place: str, exit_place: str) -> None:
    stop = stop_named(world, track_name)
    assert stop["type"] == "track", f"{track_name!r} is not a track in the itinerary: {stop}"
    entry, exit_ = PLACES[entry_place], PLACES[exit_place]
    entry_gap = distance_m(stop["entry"]["lat"], stop["entry"]["lon"], entry.lat, entry.lon)
    exit_gap = distance_m(stop["exit"]["lat"], stop["exit"]["lon"], exit_.lat, exit_.lon)
    assert entry_gap <= ENTRY_EXIT_TOLERANCE_M, f"{track_name} is entered {entry_gap:.0f} m from {entry_place}"
    assert exit_gap <= ENTRY_EXIT_TOLERANCE_M, f"{track_name} is left {exit_gap:.0f} m from {exit_place}"


def expected_road_km(world: PlannerWorld, origin: str, destination: str) -> float:
    """The road map's own rule: from where `origin` is left to where `destination` is reached."""
    left = _ends_of(world.item_named(origin))[1]
    reached = _ends_of(world.item_named(destination))[0]
    return distance_m(left["lat"], left["lon"], reached["lat"], reached["lon"]) / 1000.0 * ROAD_FACTOR


def exported_file(world: PlannerWorld) -> bytes:
    answer = world.scratch.get("export")
    assert answer is not None, "nothing was exported"
    assert answer.status_code == 200, f"the export did not download: {answer.status_code} {answer.text[:300]}"
    return bytes(answer.content)


def gpx_tracks(content: bytes) -> dict[str, list[tuple[float, float]]]:
    root = SafeXml.fromstring(content)
    return {
        _name_of(track): [_position(point) for point in track.iter(f"{{{GPX_NS}}}trkpt")]
        for track in root.iter(f"{{{GPX_NS}}}trk")
    }


def gpx_waypoints(content: bytes) -> list[str]:
    return sorted(_name_of(point) for point in SafeXml.fromstring(content).iter(f"{{{GPX_NS}}}wpt"))


def _plan_job(world: PlannerWorld, job_id: str) -> dict[str, Any]:
    answer = world.marco().plan_job(job_id)
    assert answer.status_code == 200, f"the plan job did not open: {answer.status_code} {answer.text[:300]}"
    return dict(answer.json())


def _plan_run_id(world: PlannerWorld) -> str:
    plan_run_id = world.scratch.get("plan_run_id")
    assert plan_run_id is not None, f"no plan run is ready: {_last_answer(world)}"
    return str(plan_run_id)


def _last_answer(world: PlannerWorld) -> str:
    answer = world.response
    return "no answer" if answer is None else f"{answer.status_code} {answer.text[:300]}"


def _ends_of(item: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Where an item is reached and where it is left: a place is one point, a trail runs entry -> exit."""
    return (item["entry"], item["exit"]) if item["type"] == "track" else (item["location"], item["location"])


def _name_of(element: Element) -> str:
    name = element.find(f"{{{GPX_NS}}}name")
    return "" if name is None or name.text is None else name.text


def _position(point: Element) -> tuple[float, float]:
    return (round(float(point.attrib["lat"]), 6), round(float(point.attrib["lon"]), 6))


def _stop_names(listing: str) -> list[str]:
    return re.findall(r'"([^"]+)"', listing)


# ------------------------------------------------------------------------------------- the project (Given)
@given(
    parsers.re(
        r'project "(?P<project>[^"]+)" has track "(?P<track>[^"]+)" and POIs "(?P<first>[^"]+)" and "(?P<second>[^"]+)"'
    )
)
def given_project_has_track_and_pois(world: PlannerWorld, project: str, track: str, first: str, second: str) -> None:
    ensure_project(world, project)
    for name in (track, first, second):
        ensure_item(world, name)


@given(parsers.re(r'project "(?P<project>[^"]+)" has track "(?P<track>[^"]+)" from (?P<entry>.+) to (?P<exit>.+)'))
def given_project_has_track_from_to(world: PlannerWorld, project: str, track: str, entry: str, exit: str) -> None:
    ensure_project(world, project)
    ensure_item(world, track)
    assert_track_from_to(world, track, entry, exit)


@given(parsers.re(r'"(?P<name>[^"]+)" is Start and End'))
def given_is_start_and_end(world: PlannerWorld, name: str) -> None:
    if world.project_id is None:  # slice 02 opens with this Given: the feature's trip
        ensure_project(world, FIRST_TRIP)
    ensure_item(world, name)
    set_anchors(world, name, name)
    require_success(world, f"set {name!r} as Start and End")


@given(parsers.re(r'Start is "(?P<start>[^"]+)" and End is "(?P<end>[^"]+)"'))
def given_start_is_and_end_is(world: PlannerWorld, start: str, end: str) -> None:
    ensure_project(world, FIRST_TRIP)
    ensure_item(world, start)
    ensure_item(world, end)
    set_anchors(world, start, end)
    require_success(world, f"set {start!r} as Start and {end!r} as End")


@given(parsers.re(r'"(?P<first>[^"]+)" and "(?P<second>[^"]+)" are Included'))
def given_are_included(world: PlannerWorld, first: str, second: str) -> None:
    ensure_item(world, first)
    ensure_item(world, second)


@given(parsers.re(r'"(?P<place>[^"]+)" at the entry of "(?P<track>[^"]+)" is Start and End'))
def given_place_at_entry_is_start_and_end(world: PlannerWorld, place: str, track: str) -> None:
    entry = world.item_named(track)["entry"]
    add_poi(world, place, entry["lat"], entry["lon"])
    require_success(world, f"add {place!r}")
    set_anchors(world, place, place)
    require_success(world, f"set {place!r} as Start and End")


# -------------------------------------------------------------------------------------- the plan (Given)
@given(parsers.re(r'plan run #1 of "(?P<project>[^"]+)" exists'))
def given_first_plan_run_exists(world: PlannerWorld, project: str) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} has a day trip to plan here"
    prepare_day_trip(world)
    calculate_a_plan(world)


@given(parsers.re(r"(?:Marco|he) has pressed Calculate"))
def given_has_pressed_calculate(world: PlannerWorld) -> None:
    if journey(world) is None:  # with a browser open, the press belongs to the browser run in the When
        calculate_a_plan(world)


@given("Marco pressed Calculate and the plan is still being worked out")
def given_plan_still_being_worked_out(world: PlannerWorld) -> None:
    start_a_plan_that_keeps_working(world)


@given("the optimizer could not start when the planner started")
def given_optimizer_could_not_start(world: PlannerWorld) -> None:
    world.tour_solver = UnavailableTourSolver()
    prepare_day_trip(world)


@given(
    parsers.re(
        r'Marco\'s project "(?P<project>[^"]+)" is open in his desktop browser '
        r"with the Assietta, Briancon and home as Start and End"
    )
)
def given_project_open_in_browser(world: PlannerWorld, project: str) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} has a day trip to plan here"
    server = ServerPlanner(world.environ, REPO_ROOT)  # policy: the browser needs a real server (Driving, Browser UI)
    world.planner = server
    server.start()
    prepare_day_trip(world)
    assert world.project_id is not None
    world.scratch["browser_journey"] = FirstPlanJourney(world.project_id, world.data_dir.parent / "browser")


# -------------------------------------------------------------------------------------------------- When
@when("Marco presses Calculate")
def when_marco_presses_calculate(world: PlannerWorld) -> None:
    press_calculate(world)
    if world.response is not None and world.response.status_code == 202:
        wait_for_plan(world)


@when("he presses Calculate again")
def when_he_presses_calculate_again(world: PlannerWorld) -> None:
    press_calculate(world)


@when("Marco exports the plan as GPX")
def when_marco_exports_the_plan(world: PlannerWorld) -> None:
    export_the_plan(world)


@when(parsers.re(r'(?:Marco|he) presses "Export GPX"'))
def when_presses_export_gpx(world: PlannerWorld) -> None:
    browser = journey(world)
    if browser is None:
        export_the_plan(world)
        return
    assert isinstance(world.planner, ServerPlanner)
    world.scratch["browser_run"] = browser.run(world.planner.base_url)


@when('Marco looks for "Export GPX"')
def when_marco_looks_for_export_gpx(world: PlannerWorld) -> None:
    assert world.project_id is not None, "no project is open"
    runs = world.marco().plan_runs(world.project_id)
    assert runs.status_code == 200, f"the plan runs did not open: {runs.status_code} {runs.text[:300]}"
    world.scratch["looked_at"] = (_plan_job(world, world.scratch["job_id"]), runs.json())


# ------------------------------------------------------------------------------------------ Then: itinerary
@then(parsers.re(r"he sees the stops in the order (?P<listing>\".+\")"))
def then_he_sees_the_stops_in_order(world: PlannerWorld, listing: str) -> None:
    assert_first_plan_was_added(world)
    shown = [stop["name"] for stop in stops(world)]
    assert shown == _stop_names(listing), f"the itinerary shows {shown}"


@then("each stop after the first shows its road leg in km")
def then_each_stop_shows_its_road_leg(world: PlannerWorld) -> None:
    itinerary = stops(world)
    for previous, stop in itertools.pairwise(itinerary):
        expected = expected_road_km(world, previous["name"], stop["name"])
        leg_km = stop["leg_km"]
        assert isinstance(leg_km, int | float), f"{stop['name']} shows no road leg: {stop}"
        assert abs(leg_km - expected) <= max(0.1, expected * 0.01), (
            f"leg {previous['name']} -> {stop['name']}: {leg_km} km, the road map says {expected:.1f} km"
        )


@then(parsers.re(r'the itinerary shows "(?P<track>[^"]+)" driven from (?P<entry>.+) to (?P<exit>.+)'))
def then_itinerary_shows_driven_from_to(world: PlannerWorld, track: str, entry: str, exit: str) -> None:
    assert_driven_from_to(world, track, entry, exit)


@then(parsers.re(r'the first stop is "(?P<name>[^"]+)"'))
def then_the_first_stop_is(world: PlannerWorld, name: str) -> None:
    assert_first_plan_was_added(world)
    shown = stops(world)[0]["name"]
    assert shown == name, f"the first stop is {shown!r}"


@then(parsers.re(r'the last stop is "(?P<name>[^"]+)"'))
def then_the_last_stop_is(world: PlannerWorld, name: str) -> None:
    shown = stops(world)[-1]["name"]
    assert shown == name, f"the last stop is {shown!r}"


@then(
    parsers.re(r'the leg into "(?P<track>[^"]+)" is (?P<km>\d+\.\d+) km'),
    converters={"km": float},
)
def then_the_leg_into_is(world: PlannerWorld, track: str, km: float) -> None:
    assert_first_plan_was_added(world)
    world.scratch["driven_track"] = track
    leg_km = stop_named(world, track)["leg_km"]
    assert leg_km is not None and round(leg_km, 1) == km, f"the leg into {track} is {leg_km} km"


@then(parsers.re(r"the trail is still driven from (?P<entry>.+) to (?P<exit>.+)"))
def then_the_trail_is_still_driven_from_to(world: PlannerWorld, entry: str, exit: str) -> None:
    assert_driven_from_to(world, world.scratch["driven_track"], entry, exit)


# --------------------------------------------------------------------------------------- Then: the GPX file
@then(parsers.re(r"the exported file contains its points from (?P<entry>.+) to (?P<exit>.+) in stored order"))
def then_exported_file_has_points_in_stored_order(world: PlannerWorld, entry: str, exit: str) -> None:
    assert_export_changed_nothing(world)
    exported = gpx_tracks(exported_file(world)).get(ASSIETTA)
    assert exported, f"the exported file holds no track {ASSIETTA!r}"
    # The trail file Marco imported is the oracle of the stored order (D186: no look at the planner's storage).
    assert exported == gpx_tracks(trail_file_bytes(TRACK_FILE_OF[ASSIETTA]))[ASSIETTA], (
        f"the exported points are not the trail's points in stored order ({len(exported)} points)"
    )
    for point, place in ((exported[0], PLACES[entry]), (exported[-1], PLACES[exit])):
        gap = distance_m(point[0], point[1], place.lat, place.lon)
        assert gap <= ENTRY_EXIT_TOLERANCE_M, f"{gap:.0f} m from {place.name}"


@then(parsers.re(r'he downloads "(?P<file_name>[^"]+)"'))
def then_he_downloads(world: PlannerWorld, file_name: str) -> None:
    assert_export_changed_nothing(world)
    exported_file(world)
    disposition = world.scratch["export"].headers.get("content-disposition", "")
    assert disposition.startswith("attachment"), f"not offered as a download: {disposition!r}"
    assert f'filename="{file_name}"' in disposition, f"the file is not called {file_name}: {disposition!r}"


@then("the file is standard GPX 1.1 without proprietary extensions")
def then_the_file_is_standard_gpx(world: PlannerWorld) -> None:
    content = exported_file(world)
    problems = [str(error) for error in xmlschema.XMLSchema(str(GPX_SCHEMA)).iter_errors(content.decode())]
    assert not problems, f"not valid GPX 1.1: {problems[:3]}"
    for element in SafeXml.fromstring(content).iter():
        assert element.tag.startswith(f"{{{GPX_NS}}}"), f"foreign element {element.tag}"
        assert element.tag != f"{{{GPX_NS}}}extensions", "the file has GPX extensions"
        foreign = [name for name in element.attrib if name.startswith("{") and name != SCHEMA_LOCATION_ATTRIBUTE]
        assert not foreign, f"foreign attributes {foreign} on {element.tag}"


@then(parsers.re(r'it holds track "(?P<track>[^"]+)" and the waypoints "(?P<first>[^"]+)" and "(?P<second>[^"]+)"'))
def then_it_holds_track_and_waypoints(world: PlannerWorld, track: str, first: str, second: str) -> None:
    content = exported_file(world)
    assert gpx_tracks(content).get(track), f"the file holds no track {track!r}"
    assert gpx_waypoints(content) == sorted((first, second)), f"waypoints: {gpx_waypoints(content)}"


# ---------------------------------------------------------------------------- Then: not ready, or refused
@then('"Export GPX" is not offered until the plan run is ready')
def then_export_is_not_offered_until_ready(world: PlannerWorld) -> None:
    job, runs = world.scratch["looked_at"]
    assert job["plan_run_id"] is None, f"a plan still being worked out names a plan run: {job}"
    assert [run for run in runs if run["status"] == "ready"] == [], f"a plan run is offered too early: {runs}"
    assert isinstance(world.tour_solver, HoldingTourSolver)
    world.tour_solver.let_go()  # and once it is ready, it is offered (not a planner that never offers an export)
    wait_for_plan(world)
    export_the_plan(world)
    exported_file(world)


@then("no plan run is created")
def then_no_plan_run_is_created(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {})
    assert world.response is not None and "job_id" not in world.response.json(), f"a job started: {_last_answer(world)}"


@then("only one plan run is created")
def then_only_one_plan_run_is_created(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {})  # the refused press changed nothing
    assert isinstance(world.tour_solver, HoldingTourSolver)
    world.tour_solver.let_go()  # the first press finishes: runs exist only once it does
    wait_for_plan(world)
    rows = world.after["project.plan_runs"]
    assert rows == ((1, "ready"),), f"plan runs: {rows}"


# ---------------------------------------------------------------------------------------- Then: the browser
@then("the browser shows the stops in itinerary order with their road legs")
def then_browser_shows_the_stops(world: PlannerWorld) -> None:
    run: BrowserRun = world.scratch["browser_run"]
    answer = world.marco().plan_runs(str(world.project_id))
    assert answer.status_code == 200, f"the plan runs did not open: {answer.status_code}"
    world.scratch["plan_run_id"] = str(max(answer.json(), key=lambda listed: listed["number"])["id"])
    itinerary = stops(world)
    assert len(run.stop_rows) == len(itinerary), f"the browser shows {run.stop_rows}"
    for number, (row, stop) in enumerate(zip(run.stop_rows, itinerary, strict=True)):
        assert stop["name"] in row, f"row {number + 1} should be {stop['name']!r}: {row!r}"
        if number > 0:
            assert f"{stop['leg_km']:.1f} km" in row, f"row {number + 1} shows no {stop['leg_km']:.1f} km: {row!r}"


@then(parsers.re(r'a file "(?P<file_name>[^"]+)" is downloaded'))
def then_a_file_is_downloaded(world: PlannerWorld, file_name: str) -> None:
    run: BrowserRun = world.scratch["browser_run"]
    assert run.downloaded_name == file_name, f"the browser saved {run.downloaded_name!r}"
    assert _is_gpx(run.downloaded_file), f"{file_name} is not a GPX file"


def _is_gpx(file: Path) -> bool:
    return bool(SafeXml.fromstring(file.read_bytes()).tag == f"{{{GPX_NS}}}gpx")


# ------------------------------------------------------------------------- @manual: evidence is logged by hand
@given(parsers.re(r'Marco downloaded "(?P<file_name>[^"]+)"'))
def given_marco_downloaded(world: PlannerWorld, file_name: str) -> None:
    prepare_day_trip(world)
    calculate_a_plan(world)
    export_the_plan(world)
    then_he_downloads(world, file_name)


@when("he opens it in OsmAnd on his tablet")
def when_he_opens_it_in_osmand() -> None:
    raise AssertionError("a person checks this on the tablet (docs/demo/); the scenario is @manual")


@then(parsers.re(r'OsmAnd shows "(?P<track>[^"]+)" and the waypoints "(?P<first>[^"]+)" and "(?P<second>[^"]+)"'))
def then_osmand_shows(track: str, first: str, second: str) -> None:
    raise AssertionError("a person checks this on the tablet (docs/demo/); the scenario is @manual")
