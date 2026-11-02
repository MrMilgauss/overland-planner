"""Catalog steps: projects, trails, places and trip edges (US-01b, US-02a).

Every state-changing When captures the universe before and after (Mandate 8); the Then steps assert the delta
with `assert_state_delta`, fail-closed: anything in the universe that is not expected to change must not change.
Givens reuse the When helpers (Pillar 2: the Given of scenario N is the Given + When of scenario N-1).
"""

from __future__ import annotations

from pytest_bdd import given, parsers, then, when

from tests.acceptance.overland_route_planner_mvp.steps.places import (
    ENTRY_EXIT_TOLERANCE_M,
    PLACES,
    TRAIL_FILES,
    distance_m,
    oversized_gpx_bytes,
    trail_file_bytes,
)
from tests.acceptance.overland_route_planner_mvp.steps.world import BADGE_TO_ANCHOR, CATALOG_UNIVERSE, PlannerWorld
from tests.common.predicates import gained, rows_replaced
from tests.common.state_delta import assert_state_delta

COORD = r"-?\d+(?:\.\d+)?"
FLOATS = {"lat": float, "lon": float}


# ----------------------------------------------------------------------------------------------- helpers
def create_project(world: PlannerWorld, name: str) -> None:
    world.ensure_planner()
    world.before = world.catalog_view()
    response = world.note(world.marco().create_project(name))
    if response.status_code == 201:
        world.project_id = str(response.json()["id"])
        world.project_name = name
    world.after = world.catalog_view()


def import_trail_files(world: PlannerWorld, file_name: str, megabytes: int | None = None) -> None:
    assert world.project_id is not None, "no project is open"
    content = oversized_gpx_bytes(megabytes) if megabytes else trail_file_bytes(file_name)
    world.before = world.catalog_view()
    world.note(world.marco().import_track_files(world.project_id, [(file_name, content)]))
    world.after = world.catalog_view()
    trail = TRAIL_FILES.get(file_name)
    world.last_track_name = trail.track_name if trail else None


def add_poi(world: PlannerWorld, name: str, lat: float, lon: float) -> None:
    assert world.project_id is not None, "no project is open"
    world.before = world.catalog_view()
    world.note(world.marco().add_poi(world.project_id, name, lat, lon))
    world.after = world.catalog_view()


def set_anchors(world: PlannerWorld, start: str, end: str) -> None:
    assert world.project_id is not None, "no project is open"
    start_item, end_item = world.item_named(start), world.item_named(end)
    world.before = world.catalog_view()
    world.note(world.marco().set_anchors(world.project_id, str(start_item["id"]), str(end_item["id"])))
    world.after = world.catalog_view()
    world.anchors_requested = (start, end)


def require_success(world: PlannerWorld, what: str) -> None:
    response = world.response
    assert response is not None and response.status_code < 300, (
        f"precondition failed: could not {what}: "
        f"{response.status_code if response is not None else 'no response'} "
        f"{response.text[:300] if response is not None else ''}"
    )


def assert_track_from_to(world: PlannerWorld, track_name: str, entry_place: str, exit_place: str) -> None:
    track = world.item_named(track_name)
    assert track["type"] == "track", f"{track_name!r} is not a track"
    entry, exit_ = PLACES[entry_place], PLACES[exit_place]
    entry_gap = distance_m(track["entry"]["lat"], track["entry"]["lon"], entry.lat, entry.lon)
    exit_gap = distance_m(track["exit"]["lat"], track["exit"]["lon"], exit_.lat, exit_.lon)
    assert entry_gap <= ENTRY_EXIT_TOLERANCE_M, f"{track_name} starts {entry_gap:.0f} m from {entry_place}"
    assert exit_gap <= ENTRY_EXIT_TOLERANCE_M, f"{track_name} ends {exit_gap:.0f} m from {exit_place}"


# ---------------------------------------------------------------------------------------------- projects
@given("the planner is running")
def given_the_planner_is_running(world: PlannerWorld) -> None:
    world.ensure_planner()


@given(parsers.re(r'(?:Marco|he) has created the project "(?P<name>[^"]+)"'))
def given_marco_has_created_the_project(world: PlannerWorld, name: str) -> None:
    create_project(world, name)
    require_success(world, f"create the project {name!r}")


@when(parsers.re(r'Marco creates the project "(?P<name>[^"]+)"'))
def when_marco_creates_the_project(world: PlannerWorld, name: str) -> None:
    create_project(world, name)


@when(parsers.re(r"Marco creates a project with (?P<kind>an empty name|a name of only spaces)"))
def when_marco_creates_a_project_without_a_name(world: PlannerWorld, kind: str) -> None:
    create_project(world, "" if kind == "an empty name" else "   ")


@then(parsers.re(r'he sees an empty workspace titled "(?P<name>[^"]+)"'))
def then_he_sees_an_empty_workspace_titled(world: PlannerWorld, name: str) -> None:
    assert_state_delta(
        world.before,
        world.after,
        CATALOG_UNIVERSE,
        {"projects.names": gained(name), "project.items": lambda old, new: new == ()},
    )
    opened = world.marco().project(str(world.project_id))
    assert opened.status_code == 200 and opened.json()["name"] == name


@then("no project is created")
def then_no_project_is_created(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {})


@then(parsers.re(r'the project "(?P<name>[^"]+)" is still listed'))
def then_the_project_is_still_listed(world: PlannerWorld, name: str) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {})
    assert name in world.after["projects.names"], f"{name!r} is not listed: {world.after['projects.names']}"


# ------------------------------------------------------------------------------------------------ trails
@given(parsers.re(r'he has imported "(?P<file_name>[^"]+)" into it'))
def given_he_has_imported_into_it(world: PlannerWorld, file_name: str) -> None:
    import_trail_files(world, file_name)
    require_success(world, f"import {file_name}")


@when(
    parsers.re(r'Marco imports "(?P<file_name>[^"]+)"(?: of (?P<megabytes>\d+) MB)?(?: which .+)?'),
    converters={"megabytes": lambda v: int(v) if v else None},
)
def when_marco_imports(world: PlannerWorld, file_name: str, megabytes: int | None) -> None:
    import_trail_files(world, file_name, megabytes)


@then(parsers.re(r'he sees track "(?P<track>[^"]+)" from (?P<entry>.+) to (?P<exit>.+)'))
def then_he_sees_track_from_to(world: PlannerWorld, track: str, entry: str, exit: str) -> None:
    assert_state_delta(
        world.before, world.after, CATALOG_UNIVERSE, {"project.items": gained(("track", track, True, None))}
    )
    assert_track_from_to(world, track, entry, exit)
    world.last_track_name = track


@then(parsers.re(r'it still contains track "(?P<track>[^"]+)" from (?P<entry>.+) to (?P<exit>.+)'))
def then_it_still_contains_track_from_to(world: PlannerWorld, track: str, entry: str, exit: str) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {})
    assert_track_from_to(world, track, entry, exit)


@then(
    parsers.re(r"its length matches the (?P<km>[\d.]+) km reported by Marco's GPX viewer within (?P<pct>\d+)%"),
    converters={"km": float, "pct": float},
)
def then_its_length_matches(world: PlannerWorld, km: float, pct: float) -> None:
    assert world.last_track_name is not None, "no track was looked at"
    length_km = float(world.item_named(world.last_track_name)["length_m"]) / 1000.0
    assert abs(length_km - km) <= km * pct / 100.0, f"length {length_km:.2f} km is not within {pct}% of {km} km"


@then("no track is added")
def then_no_track_is_added(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {})


# -------------------------------------------------------------------------------------------------- POIs
@given(parsers.re(rf'he has added POI "(?P<name>[^"]+)" at (?P<lat>{COORD}), (?P<lon>{COORD})'), converters=FLOATS)
def given_he_has_added_poi(world: PlannerWorld, name: str, lat: float, lon: float) -> None:
    add_poi(world, name, lat, lon)
    require_success(world, f"add POI {name!r}")


@when(parsers.re(rf'Marco adds POI "(?P<name>[^"]+)" at (?P<lat>{COORD}), (?P<lon>{COORD})'), converters=FLOATS)
def when_marco_adds_poi(world: PlannerWorld, name: str, lat: float, lon: float) -> None:
    add_poi(world, name, lat, lon)


@then(
    parsers.re(rf'"(?P<name>[^"]+)" appears in the item list as an Included POI at (?P<lat>{COORD}), (?P<lon>{COORD})'),
    converters=FLOATS,
)
def then_appears_as_included_poi(world: PlannerWorld, name: str, lat: float, lon: float) -> None:
    assert_state_delta(
        world.before, world.after, CATALOG_UNIVERSE, {"project.items": gained(("poi", name, True, None))}
    )
    location = world.item_named(name)["location"]
    assert (round(location["lat"], 6), round(location["lon"], 6)) == (round(lat, 6), round(lon, 6))


@then("no POI is added")
def then_no_poi_is_added(world: PlannerWorld) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {})


# ----------------------------------------------------------------------------------------------- anchors
@when(parsers.re(r'Marco sets "(?P<name>[^"]+)" as Start and as End'))
def when_marco_sets_round_trip(world: PlannerWorld, name: str) -> None:
    set_anchors(world, name, name)


@when(parsers.re(r'Marco sets "(?P<start>[^"]+)" as Start and "(?P<end>[^"]+)" as End'))
def when_marco_sets_one_way(world: PlannerWorld, start: str, end: str) -> None:
    set_anchors(world, start, end)


def assert_anchor_delta(world: PlannerWorld) -> None:
    assert world.anchors_requested is not None, "no Start/End was set"
    start, end = world.anchors_requested
    if start == end:
        replacements = {start: ("poi", start, True, "start_end")}
    else:
        replacements = {start: ("poi", start, True, "start"), end: ("poi", end, True, "end")}
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {"project.items": rows_replaced(replacements)})


@then(parsers.re(r'the item list shows one row "(?P<name>[^"]+)" with an S/E badge'))
def then_one_row_with_se_badge(world: PlannerWorld, name: str) -> None:
    assert_anchor_delta(world)
    rows = [row for row in world.after["project.items"] if row[1] == name]
    assert rows == [("poi", name, True, BADGE_TO_ANCHOR["S/E"])], f"rows for {name!r}: {rows}"


@then(parsers.re(r'"(?P<name>[^"]+)" shows an? (?P<badge>Start|End) badge'))
def then_shows_badge(world: PlannerWorld, name: str, badge: str) -> None:
    assert_anchor_delta(world)
    rows = [row for row in world.after["project.items"] if row[1] == name]
    assert rows == [("poi", name, True, BADGE_TO_ANCHOR[badge])], f"rows for {name!r}: {rows}"
