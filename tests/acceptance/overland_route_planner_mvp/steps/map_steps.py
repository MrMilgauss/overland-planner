"""Slice 09 steps: the map of a plan run (US-15, HC-1, FR-6.5), checked through the run's map data at the HTTP API.

`GET /api/plan-runs/{id}/geometry` answers one GeoJSON FeatureCollection (ADR-007 Amendment 2, D251): line features
`kind` road | track | retrace and point features `marker` stop | entry | exit | start_end | start | end, with the
1-based `stop` number of the itinerary row. Arrows, dashes and the "!" badge are the web's (step 10-04): at the API the
facts are the `kind`, the `level` with its `reason`, and `geometry: unavailable` with a straight two-point line.

The reference run of this feature is the canonical plan run #4 of the first trip: 9 Included items plus Start and End,
"Casa Marco, Torino" at both ends (brief section 8: "Run #4 (9 items + S/E) gives 90 pairs"; slice 04 puts the
Start at position 1 and the End at position 11). The 06a armable world has 8 items besides the anchors, so the
Given here adds one more place (`EXTRA_PLACE`): 9 items, and the itinerary is the Start, the 9 items and the End,
stops numbered 1 to 11 with a Start at 1 and an End at 11. The retrace row of a run counts as a row of the itinerary.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from pytest_bdd import given, parsers, then, when

from overland_planner.domain.catalog.coordinate import Coordinate
from tests.acceptance.overland_route_planner_mvp.steps.browser import (
    REPO_ROOT,
    MapView,
    PhoneMapJourney,
    PoiClickJourney,
    PoiClickView,
)
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import require_success, set_anchors
from tests.acceptance.overland_route_planner_mvp.steps.direction_steps import plan_run_detail, runs_by_number
from tests.acceptance.overland_route_planner_mvp.steps.places import ENTRY_EXIT_TOLERANCE_M, PLACES, distance_m
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import (
    ASSIETTA,
    FIRST_TRIP,
    HOME,
    calculate_a_plan,
    ensure_item,
    prepare_day_trip,
    stops,
)
from tests.acceptance.overland_route_planner_mvp.steps.planner import ServerPlanner
from tests.acceptance.overland_route_planner_mvp.steps.retrace_steps import (
    EXIT_REASON,
    LEG_FROM_ENTRY_KM,
    LEG_INTO_TRAIL_KM,
    anchor_item,
    arrival_of,
    departure_of,
    open_trip_with_trail,
    point_of,
    road_map,
    use_road_map,
)
from tests.acceptance.overland_route_planner_mvp.steps.routing_steps import given_plan_run_4_has_been_computed
from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld

# The places of the 06a armable world (test_slice_06a.REFERENCE_PLACES): 6 items besides the day trip's 2.
ARMABLE_WORLD_PLACES = ("Cortina d'Ampezzo", "Lago di Braies", "Aosta", "Bardonecchia", "Cuneo", "Rochemolles")
EXTRA_PLACE = "Misurina"  # the ninth item of the reference run (see the module docstring)
REFERENCE_STOPS = 11
RUN_4 = 4
COLLECTION = "FeatureCollection"
# The map's tiles are never fetched from the internet: the browser spec answers any host but the planner's with a blank
# tile. A made-up host on a made-up address (the repository is public).
BLANK_TILE_URL = "https://tiles.example.test/{z}/{x}/{y}.png"


def geometry_of(world: PlannerWorld, plan_run_id: str) -> dict[str, Any]:
    answer = world.note(world.marco().plan_run_geometry(plan_run_id))
    assert answer.status_code == 200, f"the map of the plan run did not open: {answer.status_code} {answer.text[:300]}"
    body: dict[str, Any] = answer.json()
    assert body.get("type") == COLLECTION, f"the map data is not a {COLLECTION}: {sorted(body)}"
    return body


def lines(map_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in map_data["features"] if f["geometry"]["type"] == "LineString"]


def markers(map_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in map_data["features"] if f["geometry"]["type"] == "Point"]


def props(feature: dict[str, Any]) -> dict[str, Any]:
    return dict(feature["properties"])


def opened_map(world: PlannerWorld) -> dict[str, Any]:
    assert "map_data" in world.scratch, "no map was opened"
    return dict(world.scratch["map_data"])


def place_of(point: list[float]) -> Coordinate:
    return Coordinate(point[1], point[0])  # GeoJSON order: longitude, latitude


def assert_near(point: list[float], place: str, what: str) -> None:
    gap = distance_m(point[1], point[0], PLACES[place].lat, PLACES[place].lon)
    assert gap <= ENTRY_EXIT_TOLERANCE_M, f"{what} is {gap:.0f} m from {place}"


# ---------------------------------------------------------------------------------------------------- Given
@given(parsers.re(r'plan run #4 includes "(?P<track>[^"]+)"'))
def given_plan_run_4_includes(world: PlannerWorld, track: str) -> None:
    """The reference run: the 06a armable world with one more place, 9 items and Casa Marco at both ends."""
    assert track == ASSIETTA, f"only {ASSIETTA!r} is among the items of the reference trip's run"
    world.scratch["reference_places"] = (*ARMABLE_WORLD_PLACES, EXTRA_PLACE)  # the key slice 06a's Given reads
    given_plan_run_4_has_been_computed(world, FIRST_TRIP)
    detail = plan_run_detail(world, RUN_4)
    assert any(stop["name"] == track for stop in detail["stops"]), f"plan run #4 does not include {track!r}"
    assert len(detail["stops"]) == REFERENCE_STOPS, f"plan run #4 has {len(detail['stops'])} stops, not 11"
    world.scratch["map_run_id"] = str(detail["id"])


@given(parsers.re(r'"(?P<place>[^"]+)" is Start and End of plan run #4'))
def given_the_place_is_start_and_end_of_plan_run_4(world: PlannerWorld, place: str) -> None:
    assert place == HOME, f"only {HOME!r} is Start and End of the reference trip"
    given_plan_run_4_includes(world, ASSIETTA)
    start = anchor_item(world, "start")
    assert (start["name"], start["anchor"]) == (place, "start_end"), f"the Start and End are {start}"


@given("the road shapes of its legs cannot be fetched from the routing engine")
def given_the_road_shapes_cannot_be_fetched(world: PlannerWorld) -> None:
    world.scratch["engine"].mode = "down"
    world.scratch["map_run_id"] = str(plan_run_detail(world, RUN_4)["id"])


@given(
    parsers.re(
        r'a plan run of "(?P<project>[^"]+)" has an Unconfirmed leg to "(?P<track>[^"]+)" '
        r'and a retrace of "(?P<dead_end>[^"]+)"'
    )
)
def given_a_run_with_an_unconfirmed_leg_and_a_retrace(
    world: PlannerWorld, project: str, track: str, dead_end: str
) -> None:
    """No road leaves the dead end's exit and no road open at any level reaches `track` but the one from the dead end's
    entry, which is Unconfirmed: the plan drives the dead end, retraces it, and goes on to `track` by that leg."""
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} is set up here"
    open_trip_with_trail(world, dead_end)
    ensure_item(world, track)
    dead, onward = world.item_named(dead_end), arrival_of(world.item_named(track))
    entry, exit_ = point_of(dead["entry"]), point_of(dead["exit"])
    home = departure_of(anchor_item(world, "start"))
    script = road_map(world)
    for other in world.items():
        if other["included"] and other["name"] != dead_end:
            script.none(exit_, arrival_of(other))
    script.confirmed(home, entry, LEG_INTO_TRAIL_KM)
    script.none(home, onward)
    script.unconfirmed(entry, onward, LEG_FROM_ENTRY_KM, EXIT_REASON)
    use_road_map(world)
    calculate_a_plan(world)
    rows = stops(world)
    assert [row["type"] for row in rows].count("retrace") == 1, f"the plan does not retrace {dead_end!r}"
    into = next(row for row in rows if row["name"] == track)
    assert into.get("leg_confidence") == "unconfirmed", f"the leg to {track!r} is {into.get('leg_confidence')!r}"
    world.scratch["map_run_id"] = world.scratch["plan_run_id"]


# ----------------------------------------------------------------------------------------------------- When
@when(parsers.re(r"Marco opens the map of plan run #(?P<number>\d+)"), converters={"number": int})
def when_marco_opens_the_map_of_plan_run(world: PlannerWorld, number: int) -> None:
    run_id = str(plan_run_detail(world, number)["id"])
    world.scratch["map_data"] = geometry_of(world, run_id)


@when("Marco opens its map")
def when_marco_opens_its_map(world: PlannerWorld) -> None:
    world.scratch["map_data"] = geometry_of(world, world.scratch["map_run_id"])


# ----------------------------------------------------------------------------------------------------- Then
@then(parsers.re(r'"(?P<track>[^"]+)" is drawn with arrows towards (?P<exit>.+) and with entry and exit markers'))
def then_the_track_is_drawn_towards_its_exit(world: PlannerWorld, track: str, exit: str) -> None:
    """Checked at the API: the line runs from the entry to the exit and the entry and exit markers stand there.

    That arrows are rendered along it is checked in the browser, by tests/e2e/run-map.spec.ts."""
    map_data = opened_map(world)
    (line,) = [f for f in lines(map_data) if props(f)["kind"] == "track" and props(f)["name"] == track]
    coordinates = line["geometry"]["coordinates"]
    assert_near(coordinates[0], "Pian dell'Alpe", f"the start of the line of {track!r}")
    assert_near(coordinates[-1], exit, f"the end of the line of {track!r} (the way its arrows point)")
    item_id = props(line)["item_id"]
    there = {
        props(f)["marker"]: f["geometry"]["coordinates"] for f in markers(map_data) if props(f)["item_id"] == item_id
    }
    assert there.get("entry") == coordinates[0] and there.get("exit") == coordinates[-1], (
        f"markers of {track!r}: {there}"
    )


@then("road legs are drawn in a different style from tracks")
def then_road_legs_differ_from_tracks(world: PlannerWorld) -> None:
    map_data = opened_map(world)
    kinds = {props(f)["kind"] for f in lines(map_data)}
    assert kinds == {"road", "track"}, f"the lines are of kinds {sorted(kinds)}"
    rows = world.marco().plan_run(world.scratch["map_run_id"]).json()["stops"]
    road_legs = sum(1 for row in rows if row["type"] != "retrace" and row["leg_km"] is not None)
    drawn = sum(1 for f in lines(map_data) if props(f)["kind"] == "road")
    assert drawn == road_legs, f"{drawn} road lines for {road_legs} road legs"
    tracks = sum(1 for row in rows if row["type"] == "track")
    assert sum(1 for f in lines(map_data) if props(f)["kind"] == "track") == tracks, "a track is not drawn"


@then("stops are numbered 1 to 11 in itinerary order")
def then_stops_are_numbered_1_to_11(world: PlannerWorld) -> None:
    map_data = opened_map(world)
    rows = world.marco().plan_run(world.scratch["map_run_id"]).json()["stops"]
    numbered: dict[int, str] = {}
    for f in markers(map_data):
        p = props(f)
        if p["marker"] in {"stop", "start", "end", "start_end"}:
            numbered[p["stop"]] = p["name"]
        if p.get("end_stop") is not None:
            numbered[p["end_stop"]] = p["name"]
    assert sorted(numbered) == list(range(1, REFERENCE_STOPS + 1)), f"the stop numbers are {sorted(numbered)}"
    assert [numbered[number] for number in sorted(numbered)] == [row["name"] for row in rows], "numbers out of order"


@then(parsers.re(r'"(?P<place>[^"]+)" has one combined S/E marker'))
def then_the_place_has_one_combined_marker(world: PlannerWorld, place: str) -> None:
    anchors = [props(f) for f in markers(opened_map(world)) if props(f)["marker"] in {"start", "end", "start_end"}]
    assert [(a["marker"], a["name"]) for a in anchors] == [("start_end", place)], (
        f"the Start and End markers: {anchors}"
    )
    assert (anchors[0]["stop"], anchors[0]["end_stop"]) == (1, REFERENCE_STOPS), f"the S/E marker stands for {anchors}"


@then('the road legs are drawn as dashed straight lines marked "geometry unavailable"')
def then_the_road_legs_are_straight_and_unavailable(world: PlannerWorld) -> None:
    """Checked at the API: each road line is two points marked unavailable. That the web draws them dashed and labelled
    "geometry unavailable" is checked by the web unit tests and tests/e2e/run-map.spec.ts."""
    map_data = opened_map(world)
    roads = [f for f in lines(map_data) if props(f)["kind"] == "road"]
    assert roads, "no road leg is drawn"
    for road in roads:
        assert (props(road)["geometry"], len(road["geometry"]["coordinates"])) == ("unavailable", 2), props(road)


@then("the tracks are still drawn with their direction arrows")
def then_the_tracks_are_still_drawn(world: PlannerWorld) -> None:
    """Checked at the API: each track is available and drawn from its entry to its exit. That arrows are rendered is
    checked in the browser, by tests/e2e/run-map.spec.ts."""
    map_data = opened_map(world)
    rows = world.marco().plan_run(world.scratch["map_run_id"]).json()["stops"]
    tracks = {props(f)["name"]: f for f in lines(map_data) if props(f)["kind"] == "track"}
    for row in (row for row in rows if row["type"] == "track"):
        coordinates = tracks[row["name"]]["geometry"]["coordinates"]
        assert props(tracks[row["name"]])["geometry"] == "available", f"{row['name']!r} is marked unavailable"
        assert place_of(coordinates[0]) == Coordinate(row["entry"]["lat"], row["entry"]["lon"]), (
            "not drawn from its entry"
        )
        assert place_of(coordinates[-1]) == Coordinate(row["exit"]["lat"], row["exit"]["lon"]), "not drawn to its exit"


@then('the Unconfirmed leg is drawn in the Unconfirmed style with a "!" badge')
def then_the_unconfirmed_leg_is_flagged(world: PlannerWorld) -> None:
    rows = world.marco().plan_run(world.scratch["map_run_id"]).json()["stops"]
    number = 1 + next(i for i, row in enumerate(rows) if row["name"] == ASSIETTA)
    (leg,) = [props(f) for f in lines(opened_map(world)) if props(f)["kind"] == "road" and props(f)["stop"] == number]
    assert (leg["level"], leg["reason"]) == ("unconfirmed", EXIT_REASON), f"the leg to {ASSIETTA!r} is {leg}"


@then('the retrace is drawn in its own style without direction arrows, labelled "retrace"')
def then_the_retrace_is_its_own_kind(world: PlannerWorld) -> None:
    """Checked at the API: one retrace line of its own kind, Unconfirmed, from the exit back to the entry.

    Its style, its label and the absence of arrows are checked by the web unit tests and tests/e2e/run-map.spec.ts."""
    rows = world.marco().plan_run(world.scratch["map_run_id"]).json()["stops"]
    track = next(row for row in rows if row["type"] == "track" and any(r["type"] == "retrace" for r in rows))
    retrace = next(row for row in rows if row["type"] == "retrace")
    (drawn,) = [f for f in lines(opened_map(world)) if props(f)["kind"] == "retrace"]
    coordinates = drawn["geometry"]["coordinates"]
    assert (props(drawn)["level"], props(drawn)["name"]) == ("unconfirmed", retrace["name"]), props(drawn)
    assert place_of(coordinates[0]) == Coordinate(retrace["entry"]["lat"], retrace["entry"]["lon"]), "not from the exit"
    assert place_of(coordinates[-1]) == Coordinate(retrace["exit"]["lat"], retrace["exit"]["lon"]), "not to the entry"
    assert track["name"] in retrace["name"], f"{retrace['name']!r} is not the retrace of {track['name']!r}"


# ------------------------------------------------------------------------------------- map tiles (step 10-03)
OPENTOPOMAP_URL = "https://tile.opentopomap.org/{z}/{x}/{y}.png"
OPENTOPOMAP_ATTRIBUTION = "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)"
# A made-up key on a made-up host: the repository is public, and the planner never fetches a tile.
KEYED_TILE_URL = "https://tiles.example.test/{z}/{x}/{y}.png?api_key=not-a-real-key"


@given("the planner settings choose the OpenTopoMap tiles with their attribution")
def given_the_settings_choose_opentopomap(world: PlannerWorld) -> None:
    world.environ.update({"MAP_TILE_URL": OPENTOPOMAP_URL, "MAP_TILE_ATTRIBUTION": OPENTOPOMAP_ATTRIBUTION})
    world.ensure_planner()


@given("the planner settings use a map tile address that carries a private access key")
def given_the_settings_carry_a_keyed_tile_address(world: PlannerWorld) -> None:
    world.environ["MAP_TILE_URL"] = KEYED_TILE_URL


@when("Marco opens any map")
def when_marco_opens_any_map(world: PlannerWorld) -> None:
    answer = world.note(world.marco().map_config())
    assert answer.status_code == 200, f"the map settings did not open: {answer.status_code} {answer.text[:300]}"
    world.scratch["map_config"] = answer.json()


@then("the map loads its tiles from OpenTopoMap")
def then_the_map_loads_tiles_from_opentopomap(world: PlannerWorld) -> None:
    config = world.scratch["map_config"]
    assert config["tile_url"] == OPENTOPOMAP_URL, f"the tile address is {config['tile_url']!r}"
    assert urlsplit(config["tile_url"]).hostname == "tile.opentopomap.org"
    assert isinstance(config["max_zoom"], int) and 1 <= config["max_zoom"] <= 22, f"max zoom {config['max_zoom']!r}"


@then(parsers.re(r'the attribution "(?P<credit>[^"]+)" is always shown'))
def then_the_attribution_is_always_given(world: PlannerWorld, credit: str) -> None:
    attribution = world.scratch["map_config"]["attribution"]
    assert attribution == OPENTOPOMAP_ATTRIBUTION and credit in attribution, f"the attribution is {attribution!r}"


# ------------------------------------------------------------------------------- Giulia's phone (step 10-04)
def serve_to_the_browser(world: PlannerWorld) -> ServerPlanner:
    """The browser needs a real server: the planner that computed the run is replaced by one on the same data folder."""
    if isinstance(world.planner, ServerPlanner):
        return world.planner
    assert world.planner is not None, "the planner is not running"
    world.planner.stop()
    world.environ["MAP_TILE_URL"] = BLANK_TILE_URL
    server = ServerPlanner(world.environ, REPO_ROOT)
    world.planner = server
    server.start()
    return server


@when(
    parsers.re(r"Giulia opens the map of plan run #(?P<number>\d+) on her (?P<width>\d+) px wide iPhone"),
    converters={"number": int, "width": int},
)
def when_giulia_opens_the_map_on_her_phone(world: PlannerWorld, number: int, width: int) -> None:
    """The browser needs a real server: the planner that computed the run is replaced by one on the same data folder."""
    assert width == PhoneMapJourney.SCREEN_WIDTH, f"the phone journey runs at {PhoneMapJourney.SCREEN_WIDTH} px"
    run_id = str(plan_run_detail(world, number)["id"])
    assert world.project_id is not None, "no project is open"
    serve_to_the_browser(world)
    world.scratch["map_run_id"] = run_id
    journey = PhoneMapJourney(world.project_id, world.data_dir.parent / "phone-map")
    world.scratch["map_view"] = journey.run(world.planner.base_url)


@then("she can pan and zoom")
def then_she_can_pan_and_zoom(world: PlannerWorld) -> None:
    view: MapView = world.scratch["map_view"]
    assert view.canvas_visible, "the phone shows no map"
    assert view.page_width <= view.screen_width, (
        f"the page is {view.page_width} px wide on a {view.screen_width} px screen"
    )
    assert view.panned and view.zoomed, f"the map panned: {view.panned}, zoomed: {view.zoomed}"
    assert view.credit_text.strip(), "the map shows no credit"


@then("she can read the stop numbers")
def then_she_can_read_the_stop_numbers(world: PlannerWorld) -> None:
    view: MapView = world.scratch["map_view"]
    shown = {int(digits) for text in view.numbers for digits in re.findall(r"\d+", text)}
    drawn = {
        number
        for f in markers(geometry_of(world, world.scratch["map_run_id"]))
        for number in (props(f)["stop"], props(f).get("end_stop"))
        if number is not None and props(f)["marker"] in {"stop", "start", "end", "start_end"}
    }
    assert drawn and drawn <= shown, f"the map draws stops {sorted(drawn)} but the phone showed {sorted(shown)}"


# ------------------------------------------------------------------------- POI by map click (step 10-05, US-16)
CLICK_MODE = "Click on map"
SUSA = (45.1376, 7.0486)  # the place of Marco's click; the browser clicks the pixel nearest to it, zoomed in
CLICK_PIXELS = (
    2.0  # the browser clicks the pixel nearest to the place: the POI is within these pixels of it, on the ground
)
SAME_PLACE_M = 1.0  # a click on an entry marker takes the marker's own coordinates


def open_the_day_trip_map(world: PlannerWorld) -> None:
    """The first trip with a plan run, so that its map has trails to click on."""
    prepare_day_trip(world)
    calculate_a_plan(world)


def click_on_the_map(world: PlannerWorld, action: str, name: str = "", at: tuple[float, float] = SUSA) -> None:
    """The browser run of one action on the run map; what it showed is kept for the Then steps."""
    assert world.project_id is not None, "no project is open"
    server = serve_to_the_browser(world)
    journey = PoiClickJourney(world.project_id, world.data_dir.parent / f"poi-map-{action}")
    world.scratch["poi_view"] = journey.run(server.base_url, action, name, at)


def poi_named(world: PlannerWorld, name: str) -> dict[str, Any]:
    return world.item_named(name)


@given(parsers.re(r'the map of "(?P<project>[^"]+)" is open in "Click on map" mode'))
def given_the_map_is_open_in_click_mode(world: PlannerWorld, project: str) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} has a day trip to plan here"
    open_the_day_trip_map(world)


@given(
    parsers.re(r"Marco has clicked the map at (?P<lat>[\d.]+), (?P<lon>[\d.]+)"),
    converters={"lat": float, "lon": float},
)
def given_marco_has_clicked_the_map_at(world: PlannerWorld, lat: float, lon: float) -> None:
    world.scratch["clicked_at"] = (lat, lon)


@given(parsers.re(r"Marco has clicked the map$"))
def given_marco_has_clicked_the_map(world: PlannerWorld) -> None:
    world.scratch["clicked_at"] = SUSA


@given(parsers.re(r'track "(?P<track>[^"]+)" has its entry at (?P<place>.+)'))
def given_the_track_has_its_entry_at(world: PlannerWorld, track: str, place: str) -> None:
    open_the_day_trip_map(world)
    entry = world.item_named(track)["entry"]
    assert_near([entry["lon"], entry["lat"]], place, f"the entry of {track!r}")


@given(parsers.re(r'Marco has added POI "(?P<poi>[^"]+)" by clicking the entry marker'))
def given_marco_has_added_a_poi_on_the_entry_marker(world: PlannerWorld, poi: str) -> None:
    click_on_the_map(world, "entry", poi)


@given(parsers.re(r"plan run #4 is up to date"))
def given_plan_run_4_is_up_to_date(world: PlannerWorld) -> None:
    given_plan_run_4_has_been_computed(world, FIRST_TRIP)
    run = runs_by_number(world)[RUN_4]
    assert run.get("stale") is False, f"plan run #4 is not up to date: {run}"


@when(parsers.re(r'he names the POI "(?P<name>[^"]+)"'))
def when_he_names_the_poi(world: PlannerWorld, name: str) -> None:
    click_on_the_map(world, "click", name, world.scratch["clicked_at"])


@when("he cancels the name prompt")
def when_he_cancels_the_name_prompt(world: PlannerWorld) -> None:
    """Cancel in the browser; the catalog before and after it is what `no POI is added` (slice 01a) compares."""
    serve_to_the_browser(world)
    world.before = world.catalog_view()
    click_on_the_map(world, "cancel", at=world.scratch["clicked_at"])
    world.after = world.catalog_view()
    view: PoiClickView = world.scratch["poi_view"]
    assert view.form_shown, "the click opened no name form to cancel"
    assert view.form_gone, "the name form is still open after Cancel"


@when(parsers.re(r'Marco adds "(?P<name>[^"]+)" by clicking the map'))
def when_marco_adds_a_poi_by_clicking_the_map(world: PlannerWorld, name: str) -> None:
    click_on_the_map(world, "click", name)


@when(parsers.re(r'he sets "(?P<name>[^"]+)" as Start'))
def when_he_sets_the_poi_as_start(world: PlannerWorld, name: str) -> None:
    set_anchors(world, name, HOME)
    require_success(world, f"set {name!r} as Start")


@then(
    parsers.re(r'POI "(?P<name>[^"]+)" is added at (?P<lat>[\d.]+), (?P<lon>[\d.]+)'),
    converters={"lat": float, "lon": float},
)
def then_the_poi_is_added_at(world: PlannerWorld, name: str, lat: float, lon: float) -> None:
    view: PoiClickView = world.scratch["poi_view"]
    assert view.form_shown, f"the click opened no name form (the {CLICK_MODE!r} button: {view.mode_seen})"
    where = poi_named(world, name)["location"]
    gap = distance_m(where["lat"], where["lon"], lat, lon)
    reach = CLICK_PIXELS * view.metres_per_pixel
    assert gap <= reach, (
        f"{name!r} was added {gap:.0f} m from the click, a pixel there is {view.metres_per_pixel:.1f} m"
    )
    assert view.listed, f"{name!r} is not shown in the list of trails and places"


@then(parsers.re(r'"(?P<poi>[^"]+)" is the Start at the entry coordinates of "(?P<track>[^"]+)"'))
def then_the_poi_is_the_start_at_the_entry(world: PlannerWorld, poi: str, track: str) -> None:
    start = poi_named(world, poi)
    entry = world.item_named(track)["entry"]
    assert start["anchor"] in {"start", "start_end"}, f"{poi!r} is {start['anchor']!r}, not the Start"
    gap = distance_m(start["location"]["lat"], start["location"]["lon"], entry["lat"], entry["lon"])
    assert gap <= SAME_PLACE_M, f"{poi!r} is {gap:.1f} m from the entry of {track!r}"
