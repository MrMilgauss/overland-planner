"""Slice 03b steps: a dead-end trail is driven in full and then retraced, never reversed (US-19, HC-1, FR-5.8, A-7).

Example scenarios run at layer 3 through the driving ports (D115): the HTTP API of the in-process planner built by the
production composition root (Calculate, the plan job, the plan run). Every Calculate captures the planning universe
before and after (Mandate 8). The `@property` scenario runs at layer 1-2 through `in_memory_planning` (D192), like the
slice 02 properties, on sparse generated projects.

The offline road map is scripted per pair (brief section 6, "per-pair level (`confirmed`, `unconfirmed:<reason>`,
`none`)"; policy: scripted road maps live beside the scenarios). DISTILL's proposal of the `MOCK_PLAN` pair key, which
DELIVER owns: `{from: [lat, lon], to: [lat, lon], distance_m, duration_s, level}` with `level` absent or `confirmed`
(Confirmed), `unconfirmed:<reason>` (an Unconfirmed leg, with its reason) or `none` (no road at any confidence level;
`distance_m` and `duration_s` are then left out). Every pair not listed keeps the default, straight line x 1.3.

Proposed shapes DELIVER fills (only what the scenarios read):
- plan run stops (`GET /api/plan-runs/{id}`): a retrace is its own row, `type: "retrace"`, `name: "Retrace <track>"`,
  directly after its track row; `entry` is where the retrace starts (the track's exit), `exit` where it ends (the
  track's entry); `track_km`/`offroad_s` hold the real retrace km and time (the track's own); `leg_km` is null (it is
  not a road leg); `confidence: "unconfirmed"` and `reason: "retraces the trail backwards; check it is drivable in
  reverse"`. The Gherkin's row text is composed from these fields and the place names.
- a stop reached by road also shows `leg_confidence`: `"confirmed"` or `"unconfirmed"`.
- the in-memory plan (`PlanStop`) uses `kind: "retrace"` for the same row, its `item_id` that of its track.
- a Failed plan run for an unreachable item: `failure_reason: "unreachable"`, and its report or message names the item.
- totals: `road_km` holds the road legs only; `offroad_km`/`offroad_s` hold the tracks and the retraces; no other key.
"""

from __future__ import annotations

import atexit
import functools
import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from hypothesis import example, given, seed, settings
from hypothesis import strategies as st
from pytest_bdd import given as given_step
from pytest_bdd import parsers, then, when

from overland_planner.adapters.routing.mock_routing_provider import MockRoutingProvider, read_road_map
from overland_planner.bootstrap.startup import StartupRefusedError
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.plan_run import PlanStop
from overland_planner.domain.planning.project_snapshot import left_at, reached_at
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import (
    assert_track_from_to,
    require_success,
    set_anchors,
)
from tests.acceptance.overland_route_planner_mvp.steps.direction_steps import (
    HEALTH_CHECKS,
    assert_km,
    plan_run_detail,
    runs_by_number,
    totals_of,
)
from tests.acceptance.overland_route_planner_mvp.steps.in_memory_planning import (
    GeneratedProject,
    _fixture_points,
    _place,
    assembled,
    generated_projects,
    track_item,
)
from tests.acceptance.overland_route_planner_mvp.steps.places import ENTRY_EXIT_TOLERANCE_M, PLACES, distance_m
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import (
    BRIANCON,
    FIRST_TRIP,
    HOME,
    assert_driven_from_to,
    assert_first_plan_was_added,
    calculate_a_plan,
    ensure_item,
    ensure_project,
    stops,
)
from tests.acceptance.overland_route_planner_mvp.steps.planner import InProcessPlanner
from tests.acceptance.overland_route_planner_mvp.steps.world import (
    PLANNING_UNIVERSE,
    PlannerWorld,
    assert_error_envelope,
)
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta

SOMMEILLER = "Colle del Sommeiller"
VALLE_STRETTA = "Valle Stretta"
RETRACE_REASON = "retraces the trail backwards; check it is drivable in reverse"
EXIT_REASON = "exit is 1.2 km from the nearest road - check on the ground"
ROAD_SECONDS_PER_KM = 60  # the offline road map drives at 60 km/h
# The scripted road legs of the dead-end scenarios (km); any other pair keeps the offline road map's default.
LEG_INTO_TRAIL_KM = 58.0  # Start -> the trail's entry
LEG_FROM_ENTRY_KM = 64.0  # the trail's entry -> the next stop (the retrace route onward)
LEG_FROM_EXIT_KM = 150.0  # the Unconfirmed leg from the exit, far longer than retracing and going on from the entry
OFFROAD_SPEED_KMH = 15.0  # the project's default off-road speed (FR-4.6)
KM_PRECISION = 0.05
TOTALS_KEYS = {"road_km", "road_s", "offroad_km", "offroad_s", "total_km", "total_s"}
SPARSE_ITEMS = (3, 12)  # included items of a generated sparse project, anchors among them

Point = tuple[float, float]


# ------------------------------------------------------------------------------------- the scripted road map
def point_of(coordinate: dict[str, float]) -> Point:
    """A place as the road map matches it: latitude and longitude at 6 decimals."""
    return (round(float(coordinate["lat"]), 6), round(float(coordinate["lon"]), 6))


@dataclass
class RoadMap:
    """The pairs a scenario scripts on the offline road map; every other pair keeps the default."""

    pairs: list[dict[str, Any]] = field(default_factory=list)

    def confirmed(self, origin: Point, destination: Point, km: float) -> None:
        self.pairs.append(self._measured(origin, destination, km))

    def unconfirmed(self, origin: Point, destination: Point, km: float, reason: str) -> None:
        self.pairs.append(self._measured(origin, destination, km) | {"level": f"unconfirmed:{reason}"})

    def none(self, origin: Point, destination: Point) -> None:
        self.pairs.append({"from": list(origin), "to": list(destination), "level": "none"})

    def km(self, origin: Point, destination: Point) -> float:
        """The scripted distance of one pair; a pair the scenario did not script is a mistake of the scenario."""
        for pair in self.pairs:
            if (tuple(pair["from"]), tuple(pair["to"])) == (origin, destination) and "distance_m" in pair:
                return float(pair["distance_m"]) / 1000.0
        raise AssertionError(f"the scenario scripted no road leg from {origin} to {destination}")

    def write(self, path: Path) -> None:
        path.write_text(yaml.safe_dump({"detour_factor": 1.3, "pairs": self.pairs}, sort_keys=False), encoding="utf-8")

    @staticmethod
    def _measured(origin: Point, destination: Point, km: float) -> dict[str, Any]:
        return {
            "from": list(origin),
            "to": list(destination),
            "distance_m": round(km * 1000),
            "duration_s": round(km * ROAD_SECONDS_PER_KM),
        }


def road_map(world: PlannerWorld) -> RoadMap:
    return world.scratch.setdefault("road_map", RoadMap())


def use_road_map(world: PlannerWorld) -> None:
    """The planner reads its road map when it starts (brief section 12): a running planner is restarted on it."""
    path = world.tmp_path / "retrace-road-map.yaml"
    road_map(world).write(path)
    world.environ["MOCK_PLAN"] = str(path)
    try:
        if isinstance(world.planner, InProcessPlanner):
            world.planner.environ["MOCK_PLAN"] = str(path)
            world.planner.restart()
        else:
            world.ensure_planner()
    except StartupRefusedError as refused:
        raise AssertionError(
            f"the planner refused to start with the scripted road map ({refused!r}): the offline road map does not "
            "read the per-pair `level` (confirmed, unconfirmed:<reason>, none) that slice 03b scripts"
        ) from None
    health = world.marco().health()
    assert health.status_code == 200, (
        f"the planner did not accept the road map: {health.status_code} {health.text[:300]}"
    )


def arrival_of(item: dict[str, Any]) -> Point:
    return point_of(item["entry"] if item["type"] == "track" else item["location"])


def departure_of(item: dict[str, Any]) -> Point:
    return point_of(item["exit"] if item["type"] == "track" else item["location"])


def anchor_item(world: PlannerWorld, anchor: str) -> dict[str, Any]:
    found = [item for item in world.items() if item.get("anchor") in (anchor, "start_end")]
    assert len(found) == 1, f"the trip has {len(found)} {anchor} places"
    return found[0]


# ----------------------------------------------------------------------------------------- the trip (Given)
def open_trip_with_trail(world: PlannerWorld, track: str, start: str = HOME, end: str = HOME) -> None:
    """The first trip with the trail, a Start and an End. The Gherkin names the trail only when it does not name them
    (Calculate needs a Start and an End): then the trip is the feature's round trip from home."""
    ensure_project(world, FIRST_TRIP)
    ensure_item(world, track)
    for place in (start, end):
        ensure_item(world, place)
    set_anchors(world, start, end)
    require_success(world, f"set {start!r} as Start and {end!r} as End")
    world.scratch["retrace_track"] = track


def leaves_nowhere_from_its_exit(world: PlannerWorld, track: str, towards: str) -> None:
    """No road leaves the trail's exit at any level; the entry reaches `towards`, and the Start reaches the entry."""
    item = world.item_named(track)
    entry, exit_ = point_of(item["entry"]), point_of(item["exit"])
    script = road_map(world)
    for other in world.items():
        if other["included"] and other["name"] != track:
            script.none(exit_, arrival_of(other))
    script.confirmed(departure_of(anchor_item(world, "start")), entry, LEG_INTO_TRAIL_KM)
    script.confirmed(entry, arrival_of(world.item_named(towards)), LEG_FROM_ENTRY_KM)
    use_road_map(world)


@given_step(parsers.re(r'track "(?P<track>[^"]+)" runs from (?P<entry>[^(]+?) to (?P<exit>[^(]+)'))
def given_track_runs_from_to(world: PlannerWorld, track: str, entry: str, exit: str) -> None:
    open_trip_with_trail(world, track)
    assert_track_from_to(world, track, entry, exit)


@given_step(
    parsers.re(
        r"no road leg leaves its exit at (?P<exit>.+) at any confidence level, "
        r"while one leaves its entry at (?P<entry>.+) towards the next stop"
    )
)
def given_no_road_leaves_the_exit(world: PlannerWorld, exit: str, entry: str) -> None:
    track = world.scratch["retrace_track"]
    assert_track_from_to(world, track, entry, exit)
    leaves_nowhere_from_its_exit(world, track, anchor_item(world, "end")["name"])


@given_step(
    parsers.re(r'track "(?P<track>[^"]+)" is the only item between Start "(?P<start>[^"]+)" and End "(?P<end>[^"]+)"')
)
def given_track_is_the_only_item(world: PlannerWorld, track: str, start: str, end: str) -> None:
    open_trip_with_trail(world, track, start, end)
    included = sorted(item["name"] for item in world.items() if item["included"])
    assert included == sorted({track, start, end}), f"Included: {included}"


@given_step(
    parsers.re(
        r'no road leg leaves its exit at any confidence level, while one leaves its entry towards "(?P<next>[^"]+)"'
    )
)
def given_no_road_leaves_the_exit_towards(world: PlannerWorld, next: str) -> None:
    leaves_nowhere_from_its_exit(world, world.scratch["retrace_track"], next)


@given_step(parsers.re(r"an Unconfirmed road leg leaves its exit towards the next stop"))
def given_an_unconfirmed_leg_leaves_the_exit(world: PlannerWorld) -> None:
    """Retracing and going on from the entry would be far shorter (64 km + the trail), yet a road leaves the exit."""
    track = world.item_named(world.scratch["retrace_track"])
    entry, exit_ = point_of(track["entry"]), point_of(track["exit"])
    end = arrival_of(anchor_item(world, "end"))
    script = road_map(world)
    script.confirmed(departure_of(anchor_item(world, "start")), entry, LEG_INTO_TRAIL_KM)
    script.confirmed(entry, end, LEG_FROM_ENTRY_KM)
    script.unconfirmed(exit_, end, LEG_FROM_EXIT_KM, EXIT_REASON)
    use_road_map(world)


@given_step(
    parsers.re(r'track "(?P<track>[^"]+)" whose entry cannot be reached at any confidence level but whose exit can')
)
def given_the_entry_cannot_be_reached(world: PlannerWorld, track: str) -> None:
    open_trip_with_trail(world, track)
    item = world.item_named(track)
    entry, exit_ = point_of(item["entry"]), point_of(item["exit"])
    home = departure_of(anchor_item(world, "start"))
    script = road_map(world)
    script.none(home, entry)  # nothing arrives at the entry, at any level
    script.confirmed(home, exit_, LEG_INTO_TRAIL_KM)  # the exit can be reached, and left
    script.confirmed(exit_, home, LEG_FROM_ENTRY_KM)
    use_road_map(world)


@given_step(
    parsers.re(r'a plan of "(?P<project>[^"]+)" retraces "(?P<track>[^"]+)" \((?P<km>[\d.]+) km\)'),
    converters={"km": float},
)
def given_a_plan_retraces(world: PlannerWorld, project: str, track: str, km: float) -> None:
    """The chain of the first scenario (Pillar 2): the dead-end trail, its road map, Calculate, and what it gave."""
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} is set up here"
    open_trip_with_trail(world, track)
    leaves_nowhere_from_its_exit(world, track, anchor_item(world, "end")["name"])
    calculate_a_plan(world)
    rows = stops(world)
    assert [row["type"] for row in rows].count("retrace") == 1, f"the plan does not retrace {track!r}: {names(rows)}"
    length_km = float(world.item_named(track)["length_m"]) / 1000.0
    assert abs(length_km - km) <= KM_PRECISION, f"{track!r} is {length_km:.2f} km long, not {km} km"
    world.scratch["retrace_km"] = km


@given_step(
    parsers.re(
        r"two dead-end trails can each be reached either with a retrace or by a Confirmed order "
        r"that is (?P<km>\d+) km longer"
    ),
    converters={"km": int},
)
def given_two_dead_ends_and_a_longer_confirmed_order(world: PlannerWorld, km: int) -> None:
    """Casa -> trail 1 -> trail 2 -> Casa by Confirmed legs only, against retracing both (or only the first)."""
    ensure_project(world, FIRST_TRIP)
    for name in (SOMMEILLER, VALLE_STRETTA, HOME):
        ensure_item(world, name)
    set_anchors(world, HOME, HOME)
    require_success(world, f"set {HOME!r} as Start and End")
    first, second = world.item_named(SOMMEILLER), world.item_named(VALLE_STRETTA)
    home = arrival_of(world.item_named(HOME))
    a1, b1, a2, b2 = arrival_of(first), departure_of(first), arrival_of(second), departure_of(second)
    script = road_map(world)
    for origin, destination, leg_km in (  # the road between the starts of the trails and home, both ways
        (home, a1, 40.0),
        (home, a2, 40.0),
        (a1, home, 40.0),
        (a2, home, 40.0),
        (a1, a2, 20.0),
        (a2, a1, 20.0),
        (b1, a2, 52.0),  # the only road out of the first trail's exit: onward to the second trail, Confirmed
        (b2, home, 60.0),  # the only road out of the second trail's exit: home, Confirmed
    ):
        script.confirmed(origin, destination, leg_km)
    script.none(b1, home)
    script.none(b2, a1)
    retrace_km = (float(first["length_m"]) + float(second["length_m"])) / 1000.0
    confirmed_order = script.km(home, a1) + script.km(b1, a2) + script.km(b2, home)
    both_retraced = script.km(home, a2) + script.km(a2, a1) + script.km(a1, home) + retrace_km
    first_retraced = script.km(home, a1) + script.km(a1, a2) + script.km(b2, home) + float(first["length_m"]) / 1000.0
    assert abs(both_retraced + km - confirmed_order) <= 0.2, (
        f"the scripted Confirmed order is {confirmed_order:.1f} km, the retrace order {both_retraced:.1f} km: "
        f"not {km} km longer"
    )
    assert first_retraced >= both_retraced, "retracing only the first trail would be the shortest retrace order"
    use_road_map(world)
    world.scratch["confirmed_legs_km"] = [None, script.km(home, a1), script.km(b1, a2), script.km(b2, home)]


# ---------------------------------------------------------------------------------------------- the results
def latest_plan_run(world: PlannerWorld) -> dict[str, Any]:
    return plan_run_detail(world, max(runs_by_number(world)))


def names(rows: list[dict[str, Any]]) -> list[str]:
    return [row["name"] for row in rows]


def retrace_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["type"] == "retrace"]


def index_of(rows: list[dict[str, Any]], name: str) -> int:
    matches = [number for number, row in enumerate(rows) if row["name"] == name]
    assert len(matches) == 1, f"expected {name!r} once in the itinerary, found {len(matches)}: {names(rows)}"
    return matches[0]


def row_after(rows: list[dict[str, Any]], number: int, what: str) -> dict[str, Any]:
    assert number + 1 < len(rows), f"there is no {what} after {rows[number]['name']!r}: {names(rows)}"
    return rows[number + 1]


def retrace_after_its_track(rows: list[dict[str, Any]], track: str) -> dict[str, Any]:
    retrace = row_after(rows, index_of(rows, track), "row")
    assert retrace["type"] == "retrace", f"the row after {track!r} is {retrace['name']!r} ({retrace['type']})"
    assert retrace["name"] == f"Retrace {track}", f"the retrace row is called {retrace['name']!r}"
    assert len(retrace_rows(rows)) == 1, f"the plan retraces {len(retrace_rows(rows))} times: {names(rows)}"
    return retrace


def assert_at(row: dict[str, Any], key: str, place: str, what: str) -> None:
    point = row.get(key)
    assert point is not None, f"{what} shows no {key} point: {row}"
    gap = distance_m(point["lat"], point["lon"], PLACES[place].lat, PLACES[place].lon)
    assert gap <= ENTRY_EXIT_TOLERANCE_M, f"{what} has its {key} {gap:.0f} m from {place}"


# ------------------------------------------------------------------------------------ Then: the first scenario
@then(parsers.re(r'the itinerary shows "(?P<track>[^"]+?)  (?P<entry>[^"]+) -> (?P<exit>[^"]+)" driven in full'))
def then_the_itinerary_shows_driven_in_full(world: PlannerWorld, track: str, entry: str, exit: str) -> None:
    assert_first_plan_was_added(world)
    assert_driven_from_to(world, track, entry, exit)
    row = stops(world)[index_of(stops(world), track)]
    stored_km = float(world.item_named(track)["length_m"]) / 1000.0
    assert_km(row.get("track_km"), stored_km, f"{track} driven")


@then(
    parsers.re(
        r'the next row is "Retrace (?P<track>[^"]+) \((?P<start>[^)]+) -> (?P<end>[^)]+)\) - '
        r'Unconfirmed: (?P<reason>[^"]+)"'
    )
)
def then_the_next_row_is_the_retrace(world: PlannerWorld, track: str, start: str, end: str, reason: str) -> None:
    rows = stops(world)
    retrace = retrace_after_its_track(rows, track)
    assert_at(retrace, "entry", start, retrace["name"])  # the retrace starts where the trail ends
    assert_at(retrace, "exit", end, retrace["name"])  # and ends where the trail begins
    assert retrace.get("confidence") == "unconfirmed", f"the retrace is {retrace.get('confidence')!r}, not Unconfirmed"
    assert retrace.get("reason") == reason, f"the retrace says {retrace.get('reason')!r}, not {reason!r}"
    assert retrace["leg_km"] is None, f"the retrace is shown as a road leg of {retrace['leg_km']} km"
    stored_km = float(world.item_named(track)["length_m"]) / 1000.0
    assert_km(retrace.get("track_km"), stored_km, "the retrace")  # the real km, no penalty in it


@then(parsers.re(r"the next stop is reached from (?P<place>.+)"))
def then_the_next_stop_is_reached_from(world: PlannerWorld, place: str) -> None:
    rows = stops(world)
    track = world.scratch["retrace_track"]
    retrace = retrace_after_its_track(rows, track)
    onward = row_after(rows, index_of(rows, retrace["name"]), "stop")
    assert_at(retrace, "exit", place, "the retrace")  # where the road onward starts
    expected = road_map(world).km(
        point_of(world.item_named(track)["entry"]), arrival_of(world.item_named(onward["name"]))
    )
    assert_km(onward["leg_km"], expected, f"the road into {onward['name']}")
    assert onward.get("leg_confidence") == "confirmed", f"the road leg is {onward.get('leg_confidence')!r}"


# ------------------------------------------------------------------------------ Then: the unreachable trail
@then(parsers.re(r'"(?P<item>[^"]+)" is reported as Failed with reason "(?P<reason>[^"]+)"'))
def then_the_item_is_reported_failed(world: PlannerWorld, item: str, reason: str) -> None:
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((1, "failed"))})
    detail = latest_plan_run(world)
    assert detail.get("failure_reason") == reason, f"plan run #1 fails with {detail.get('failure_reason')!r}"
    report = detail.get("report") or {}
    texts = [*world.seen_messages, str(report.get("reason") or ""), *(detail.get("messages") or ())]
    assert any(item in text for text in texts), f"nothing Marco read names {item!r}: {texts}"


@then(parsers.re(r'no plan enters "(?P<track>[^"]+)" from its exit'))
def then_no_plan_enters_from_its_exit(world: PlannerWorld, track: str) -> None:
    detail = latest_plan_run(world)
    assert detail["stops"] == [] and detail["totals"] is None, f"a Failed run shows a plan: {names(detail['stops'])}"
    export = world.marco().export_gpx(str(detail["id"]))
    assert export.status_code == 422, f"the Failed run's plan can be exported: {export.status_code}"
    assert_error_envelope(export)


@then("the plan run is Failed")
def then_the_plan_run_is_failed(world: PlannerWorld) -> None:
    runs = runs_by_number(world)
    assert [(number, run["status"]) for number, run in sorted(runs.items())] == [(1, "failed")], f"plan runs: {runs}"


# ----------------------------------------------------------------------------------- Then: no retrace needed
@then("no retrace is planned")
def then_no_retrace_is_planned(world: PlannerWorld) -> None:
    assert_first_plan_was_added(world)
    rows = stops(world)
    assert names(rows)[0] == HOME and len(rows) >= 3, f"the plan is {names(rows)}"
    assert retrace_rows(rows) == [], f"the plan retraces: {names(retrace_rows(rows))}"


@then(parsers.re(r"the plan uses the Unconfirmed road leg from (?P<place>.+)"))
def then_the_plan_uses_the_unconfirmed_leg(world: PlannerWorld, place: str) -> None:
    rows = stops(world)
    track = world.scratch["retrace_track"]
    assert_at(rows[index_of(rows, track)], "exit", place, track)
    onward = row_after(rows, index_of(rows, track), "stop")
    assert_km(onward["leg_km"], LEG_FROM_EXIT_KM, f"the road into {onward['name']}")  # the leg from the exit
    assert onward.get("leg_confidence") == "unconfirmed", f"the road leg is {onward.get('leg_confidence')!r}"


# ------------------------------------------------------------------------------- Then: a retrace in the results
@when("Marco opens its results")
def when_marco_opens_its_results(world: PlannerWorld) -> None:
    world.scratch["opened_run"] = latest_plan_run(world)


def opened_rows(world: PlannerWorld) -> list[dict[str, Any]]:
    return list(world.scratch["opened_run"]["stops"])


@then("the retrace is listed as its own leg directly after the track")
def then_the_retrace_is_its_own_leg(world: PlannerWorld) -> None:
    retrace_after_its_track(opened_rows(world), world.scratch["retrace_track"])


@then(
    parsers.re(r"its (?P<km>[\d.]+) km and duration are included in the off-road totals with no separate breakdown"),
    converters={"km": float},
)
def then_its_km_are_in_the_offroad_totals(world: PlannerWorld, km: float) -> None:
    rows = opened_rows(world)
    track = world.scratch["retrace_track"]
    retrace = retrace_after_its_track(rows, track)
    assert_km(retrace.get("track_km"), km, "the retrace")
    assert retrace.get("offroad_s") is not None, f"the retrace shows no duration: {retrace}"
    trail_s = rows[index_of(rows, track)]["offroad_s"]
    assert abs(retrace["offroad_s"] - trail_s) <= 1.0, (
        f"the retrace takes {retrace['offroad_s']} s, the trail {trail_s} s"
    )
    totals = totals_of(world.scratch["opened_run"])
    assert set(totals) == TOTALS_KEYS, f"the totals show {sorted(totals)}: a retrace has no breakdown of its own"
    driven_off_road = [row for row in rows if row["type"] in ("track", "retrace")]
    assert_km(totals["offroad_km"], 2 * km, "off-road")  # the trail and its retrace
    assert abs(totals["offroad_s"] - sum(row["offroad_s"] for row in driven_off_road)) <= 1.0, f"totals: {totals}"
    assert abs(totals["offroad_s"] - 2 * km / OFFROAD_SPEED_KMH * 3600) <= 60, f"off-road time: {totals}"


@then("the road and off-road totals hold only distance actually driven")
def then_the_totals_hold_only_distance_driven(world: PlannerWorld) -> None:
    detail = world.scratch["opened_run"]
    totals, rows = totals_of(detail), opened_rows(world)
    legs = [row for row in rows if row["leg_km"] is not None]
    assert_km(totals["road_km"], sum(row["leg_km"] for row in legs), "road")  # no penalty, no retrace in it
    assert totals["road_s"] == sum(row["leg_s"] for row in legs), f"road time: {totals}"
    assert_km(totals["road_km"], LEG_INTO_TRAIL_KM + LEG_FROM_ENTRY_KM, "road")
    assert_km(totals["offroad_km"], sum(row["track_km"] for row in rows if row["track_km"] is not None), "off-road")
    assert_km(totals["total_km"], totals["road_km"] + totals["offroad_km"], "total")
    assert abs(totals["total_s"] - (totals["road_s"] + totals["offroad_s"])) <= 1.0, f"total time: {totals}"


# --------------------------------------------------------------------------- Then: the End, and the order won
@then(parsers.re(r'the plan drives "(?P<track>[^"]+)", retraces it, and ends at "(?P<end>[^"]+)"'))
def then_the_plan_drives_retraces_and_ends(world: PlannerWorld, track: str, end: str) -> None:
    assert_first_plan_was_added(world)
    rows = stops(world)
    start = anchor_item(world, "start")["name"]
    assert names(rows) == [start, track, f"Retrace {track}", end], f"the plan is {names(rows)}"
    assert [row["type"] for row in rows] == ["poi", "track", "retrace", "poi"], f"the rows are {rows}"
    assert_km(rows[1]["leg_km"], LEG_INTO_TRAIL_KM, f"the road into {track}")
    assert_km(rows[3]["leg_km"], LEG_FROM_ENTRY_KM, f"the road into {end}")  # from the trail's entry, not its exit


@then("the plan uses the Confirmed order without any retrace")
def then_the_plan_uses_the_confirmed_order(world: PlannerWorld) -> None:
    assert_first_plan_was_added(world)
    rows = stops(world)
    assert names(rows) == [HOME, SOMMEILLER, VALLE_STRETTA, HOME], f"the plan is {names(rows)}"
    assert retrace_rows(rows) == [], f"the plan retraces: {names(retrace_rows(rows))}"
    for row, km in zip(rows, world.scratch["confirmed_legs_km"], strict=True):
        if km is None:
            assert row["leg_km"] is None, f"{row['name']} has a road leg into it"
        else:
            assert_km(row["leg_km"], km, f"the road into {row['name']}")
            assert row.get("leg_confidence") == "confirmed", (
                f"the road into {row['name']} is {row.get('leg_confidence')!r}"
            )


# ----------------------------------------------------------------------------------------- the property pieces
@functools.cache
def road_map_dir() -> Path:
    folder = Path(tempfile.mkdtemp(prefix="retrace-road-maps-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    return folder


@dataclass(frozen=True, repr=False)
class SparseProject(GeneratedProject):
    """A generated project whose `dead_ends` (track ids) have no road leg leaving their exit, at any level."""

    dead_ends: frozenset[str] = frozenset()

    def __repr__(self) -> str:
        return f"{super().__repr__()[:-1]}, dead ends {sorted(self.dead_ends)})"

    def road_map_provider(self) -> MockRoutingProvider:
        if not self.dead_ends:
            return MockRoutingProvider()
        listed = [item for item in self.snapshot.items if item.included]
        pairs = []
        for item in listed:
            if item.id in self.dead_ends:
                origin = left_at(item)
                for other in sorted({reached_at(o) for o in listed if o.id != item.id}, key=_latlon):
                    pairs.append({"from": list(_latlon(origin)), "to": list(_latlon(other)), "level": "none"})
        text = yaml.safe_dump({"detour_factor": 1.3, "pairs": pairs}, sort_keys=False)
        path = road_map_dir() / f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.yaml"
        path.write_text(text, encoding="utf-8")
        try:
            return MockRoutingProvider(script=read_road_map(path))
        except ValueError as unreadable:
            raise AssertionError(
                f"the offline road map does not read the per-pair `level: none` of slice 03b: {unreadable}"
            ) from None


def _latlon(coordinate: Coordinate) -> Point:
    return (coordinate.latitude, coordinate.longitude)


def _lonely_exits(project: GeneratedProject) -> list[str]:
    """The tracks whose exit is a point of their own: no loop, and no other item starts, ends or sits there."""
    seen: list[Coordinate] = []
    for item in project.snapshot.items:
        seen += [item.entry, item.exit] if isinstance(item, TrackItem) else [item.location]
    return [
        item.id
        for item in project.snapshot.items
        if isinstance(item, TrackItem) and item.included and item.exit != item.entry and seen.count(item.exit) == 1
    ]


@st.composite
def sparse_projects(draw: st.DrawFn, low: int, high: int) -> SparseProject:
    """Generated projects (D192) in which some tracks are dead ends: no road leaves their exit."""
    project = draw(generated_projects(low, high))
    lonely = _lonely_exits(project)
    chosen = draw(st.lists(st.sampled_from(lonely), min_size=1, unique=True)) if lonely else []
    return SparseProject(project.snapshot, project.files, f"sparse {project.label}", frozenset(chosen))


def _sparse(project: GeneratedProject, *dead_ends: str) -> SparseProject:
    return SparseProject(project.snapshot, project.files, f"sparse {project.label}", frozenset(dead_ends))


def sommeiller_round_trip() -> SparseProject:
    """A-7 / US-19 S1: the Sommeiller is a dead end, in a round trip from Casa Marco."""
    home = _place("home", HOME)
    trail = track_item("sommeiller", SOMMEILLER, _fixture_points("colle-del-sommeiller.gpx"))
    return _sparse(assembled(home, home, [trail], "Sommeiller round trip from Casa Marco"), "sommeiller")


def sommeiller_on_the_way_to_briancon() -> SparseProject:
    """The Sommeiller (dead end) and the Assietta on the way from Casa Marco to Briancon."""
    start, end = _place("start", HOME), _place("end", BRIANCON)
    others: list[tuple[CatalogItem, bytes | None]] = [
        track_item("assietta", "Strada dell'Assietta", _fixture_points("assietta.gpx")),
        track_item("sommeiller", SOMMEILLER, _fixture_points("colle-del-sommeiller.gpx")),
        (_place("passo", "Passo Giau"), None),
    ]
    return _sparse(assembled(start, end, others, "Sommeiller and the Assietta, Casa Marco to Briancon"), "sommeiller")


def retraced_tracks(project: SparseProject, plan_stops: tuple[PlanStop, ...]) -> list[str]:
    """What the guarded form requires of every retrace leg; returns the tracks retraced, in plan order."""
    tracks = {item.id: item for item in project.snapshot.items if isinstance(item, TrackItem)}
    retraced = []
    for number, stop in enumerate(plan_stops):
        if stop.kind != "retrace":
            continue
        before = plan_stops[number - 1] if number else None
        assert before is not None and before.kind == "track" and before.item_id == stop.item_id, (
            f"the retrace of {stop.item_id} does not follow its own track: {[(s.kind, s.item_id) for s in plan_stops]}"
        )
        track = tracks[stop.item_id]
        assert (stop.entry, stop.exit) == (track.exit, track.entry), (
            f"the retrace of {track.id} runs {stop.entry} -> {stop.exit}, not exit {track.exit} -> entry {track.entry}"
        )
        retraced.append(stop.item_id)
    return retraced


def reversed_track_stops(project: SparseProject, plan_stops: tuple[PlanStop, ...]) -> list[str]:
    """The tracks whose stop does not run from the stored entry to the stored exit (a loop has the same end twice)."""
    tracks = {item.id: item for item in project.snapshot.items if isinstance(item, TrackItem)}
    wrong = []
    for stop in plan_stops:
        if stop.kind == "track":
            track = tracks[stop.item_id]
            if (stop.entry, stop.exit) != (track.entry, track.exit):
                wrong.append(stop.item_id)
    return wrong


@given_step(
    parsers.re(r"(?P<count>\d+) randomly generated sparse projects with missing road legs at track exits"),
    converters={"count": int},
)
def given_randomly_generated_sparse_projects(world: PlannerWorld, count: int) -> None:
    profile_examples = (
        settings.default.max_examples
    )  # profile ci runs the Gherkin's count; dev and mutation fewer (D192)
    world.scratch["cases"] = count if profile_examples >= 1_000 else min(count, profile_examples)
    world.scratch["projects"] = sparse_projects(*SPARSE_ITEMS)


def for_every_sparse_project(world: PlannerWorld, check: Any) -> None:
    def body(project: SparseProject) -> None:
        check(project)

    run = given(project=world.scratch["projects"])(body)
    for pinned in (sommeiller_round_trip(), sommeiller_on_the_way_to_briancon()):
        run = example(project=pinned)(run)
    run = settings(max_examples=world.scratch["cases"], deadline=None, suppress_health_check=HEALTH_CHECKS)(run)
    seed(world.scratch["seed"])(run)()


@then("no track item is ever driven from exit to entry")
def then_no_track_is_driven_backwards(world: PlannerWorld) -> None:
    def check(project: SparseProject) -> None:
        plan = world.scratch["plan"](project)
        assert reversed_track_stops(project, plan.stops) == [], f"a track is not driven entry -> exit: {plan.stops}"
        driven = [stop.item_id for stop in plan.stops if stop.kind == "track"]
        assert sorted(driven) == sorted(track.id for track in project.tracks_to_drive()), f"tracks driven: {driven}"

    for_every_sparse_project(world, check)


@then("every retrace leg follows its own track from exit back to entry directly after that track")
def then_every_retrace_follows_its_track(world: PlannerWorld) -> None:
    def check(project: SparseProject) -> None:
        plan = world.scratch["plan"](project)
        retraced = retraced_tracks(project, plan.stops)
        driven_dead_ends = sorted(track.id for track in project.tracks_to_drive() if track.id in project.dead_ends)
        assert sorted(retraced) == driven_dead_ends, (  # exactly where no road leaves the exit, once each
            f"retraced {sorted(retraced)}, dead ends driven {driven_dead_ends}"
        )

    for_every_sparse_project(world, check)
