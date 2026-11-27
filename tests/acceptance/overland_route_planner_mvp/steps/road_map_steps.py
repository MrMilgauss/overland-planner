"""Slice 12c steps at the HTTP API (US-27 to US-31): the road map the planner serves, the change the owner plans, the
coverage of a trip and the place search. No production module is imported (D292's rule): every step goes through the
planner's driving ports, so until DELIVER builds the routes and settings the Thens fail on what the planner answers (a
business reason: 404 where a road map is expected), not on an import.

Gherkin speaks business language; the storage details (map folders, the pending change's lines, the helper's files)
live here, in the step bodies, and are read only by the `@real-io @adapter-integration` scenarios.

What the steps pin where DESIGN (D308, "Driving ports") names fields but leaves a spelling open is marked PIN: the
catalogue answer is a list of `{key, name, parent_name, bytes, in_map}`; the preview/summary answer carries
`added`, `removed`, `total_bytes`, `estimate{total_minutes, pause_minutes}`, `land_groups[{regions}]` and
`not_linked_note`; a map of unknown coverage still gives `served.map_date`; a change refused for lack of a helper is
a 503 `rebuilds_not_set_up` (D315). DELIVER adjusts a PIN with the route in the same commit.

Mandate 8: the steps that change what the owner can see (a change planned or cancelled) compare the view
`{road_map.regions, road_map.map_date, road_map.change_state}` before and after with `assert_state_delta`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pytest_bdd import given, parsers, then, when

from tests.acceptance.overland_route_planner_mvp.steps.road_map_fakes import (
    EIGHT,
    GB,
    RecordingServer,
    build_volume,
    catalogue_features,
    epoch_of,
    feature_by_key,
    gpx_of,
    key_of,
    place_search_service,
    region_service,
)
from tests.acceptance.overland_route_planner_mvp.steps.routing_steps import SyntheticValhalla
from tests.acceptance.overland_route_planner_mvp.steps.world import CATALOG_UNIVERSE, PlannerWorld
from tests.common.fakes import FakeClock
from tests.common.state_delta import assert_state_delta, set_to, unchanged

RM_UNIVERSE = {"road_map.regions", "road_map.map_date", "road_map.change_state", "queue.files"}
PLACES_AT = {
    "Torino": (45.0703, 7.6869),
    "Cadaques": (42.2889, 3.2776),
    "Lagos": (37.1028, -8.6730),
    "Chefchaouen": (35.1688, -5.2636),
    "Moab": (38.5733, -109.5498),
}
NOW = datetime(2026, 11, 28, 21, 0, tzinfo=UTC)
FALLBACK_EPOCH = 1_793_000_000
# What the owner reads -> (code, words the message must hold). The CODE is the key of the refusal (D308), the wording
# is only checked for the figures. A reason this table does not know fails with an AssertionError naming it.
REFUSALS: dict[str, tuple[str | None, list[str]]] = {
    "it contains Rhone-Alpes, which is already in the map": ("overlaps_region", ["Rhone-Alpes"]),
    "the download would be 20.4 GB and the limit is 8 GB": ("too_big", ["20.4", "8 GB"]),
    "that region is not in the catalogue": ("unknown_region", []),
    "a change is already pending": ("change_pending", []),
    "a map was built today": ("same_day", []),
    "the start time is not valid": ("bad_start", []),
    "changes are not available": ("changes_unavailable", []),
    "rebuilds are not set up on the Pi": ("rebuilds_not_set_up", ["not set up"]),
}
FAILURES = {  # what the owner is told a rebuild stopped for -> the failure code the helper writes (D303, D314)
    "a deploy kept the Pi busy for half an hour": "locked",
    "a map was already built that day": "date",
    "the disk was too small": "disk",
    "the memory was too small": "memory",
    "the routing engine did not answer": "routing_status",
    "a download failed": "download",
    "a region's border file was not found": "region_missing",
    "the regions could not be merged": "merge",
    "the map could not be built": "build",
    "the Pi ran out of memory building the map": "build_oom",
    "the road rules could not be applied": "overrides",
    "the new map could not be put in place": "promote",
    "the new map did not start": "switch",
    "the Pi lost power": "interrupted",
}


class RealClock:
    """The wall clock, for the scenarios that measure real seconds between two requests (the place search)."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def probe(self) -> Any:
        return FakeClock().probe()


class ScriptedEngine(SyntheticValhalla):
    """The routing engine behind the planner's transport seam; `/status` carries the map date the scenario sets."""

    def __init__(self) -> None:
        super().__init__()
        self.epoch = FALLBACK_EPOCH

    def __call__(self, request: httpx.Request) -> httpx.Response:
        response = super().__call__(request)
        if request.url.path == "/status" and response.status_code == 200:
            body = response.json()
            body["tileset_last_modified"] = self.epoch
            return httpx.Response(200, json=body)
        return response


@dataclass
class RoadMapState:
    root: Path
    region_server: RecordingServer | None = None
    place_server: RecordingServer | None = None
    place_mode: str = "healthy"
    place_on: bool = True
    place_off: bool = False
    place_url_empty: bool = False
    served: list[str] = field(default_factory=list)
    served_name: str = ""
    engine: ScriptedEngine | None = None
    response: httpx.Response | None = None
    answers: list[httpx.Response] = field(default_factory=list)
    view_before: dict[str, Any] = field(default_factory=dict)
    view_after: dict[str, Any] = field(default_factory=dict)
    last_item_id: str | None = None
    last_item_name: str = ""
    items_before: dict[str, Any] = field(default_factory=dict)
    clock_set: bool = False
    helper_set: bool = False
    changes_blocked: bool = False


# ------------------------------------------------------------------------------------------------------- the world
def state(world: PlannerWorld) -> RoadMapState:
    if "rm" not in world.scratch:
        world.scratch["rm"] = RoadMapState(root=world.tmp_path / "road-map-volume")
    rm: RoadMapState = world.scratch["rm"]
    return rm


def arm(world: PlannerWorld) -> RoadMapState:
    """Point the planner's settings at this scenario's volume and its two local fake services (never the internet)."""
    rm = state(world)
    if rm.region_server is None:
        rm.region_server = region_service()
    if rm.place_server is None and rm.place_on and not rm.place_url_empty:
        rm.place_server = place_search_service(rm.place_mode)
    changes = rm.root / "changes"
    if rm.changes_blocked:
        rm.root.mkdir(parents=True, exist_ok=True)
        if changes.is_dir():
            shutil.rmtree(changes)
        changes.write_text("not a folder\n")
    else:
        changes.mkdir(parents=True, exist_ok=True)
    if not rm.clock_set:
        world.clock = FakeClock(NOW)
        rm.clock_set = True
    if not rm.helper_set:  # the helper of the Pi has just looked (D303): rebuilds are set up unless a scenario says not
        seen = changes / "helper-seen"
        seen.touch()
        stamp = world.clock.now().timestamp()
        os.utime(seen, (stamp, stamp))
        rm.helper_set = True
    world.environ.update(
        ROAD_MAP_DIR=str(rm.root / "tilesets"),
        ROAD_MAP_CHANGES_DIR=str(changes),
        GEOFABRIK_INDEX_URL=f"{rm.region_server.url}/index-v1-nogeom.json",
        PLACE_SEARCH="off" if rm.place_off else "on",
        PLACE_SEARCH_URL=f"{rm.place_server.url}/search" if rm.place_server is not None else "",
    )
    if rm.engine is None and "ROAD_MAP_SERVED_TILESET" not in world.environ:
        world.environ["ROAD_MAP_SERVED_TILESET"] = rm.served_name
    return rm


def planner(world: PlannerWorld) -> RoadMapState:
    rm = arm(world)
    world.ensure_planner()
    return rm


def call(world: PlannerWorld, method: str, url: str, **kwargs: Any) -> httpx.Response:
    rm = planner(world)
    rm.response = world.note(world.marco().call(method, url, **kwargs))
    rm.answers.append(rm.response)
    return rm.response


def road_map(world: PlannerWorld) -> dict[str, Any]:
    answer = call(world, "GET", "/api/road-map")
    assert answer.status_code == 200, f"the planner has no road map to show: {answer.status_code} {answer.text[:200]}"
    body: dict[str, Any] = answer.json()
    return body


def only(rows: list[Any], what: str) -> Any:
    assert len(rows) == 1, f"expected one of the {what}, found {len(rows)}"
    return rows[0]


def last_two(rows: list[Any], what: str) -> tuple[Any, Any]:
    assert len(rows) >= 2, f"expected two of the {what}, found {len(rows)}"
    return rows[-2], rows[-1]


def names_of(rows: list[Any]) -> list[str]:
    return [str(r["name"]) if isinstance(r, dict) else str(r) for r in rows]


def rm_view(world: PlannerWorld) -> dict[str, Any]:
    body = road_map(world)
    served = body["served"]
    changes = state(world).root / "changes"
    return {
        "queue.files": tuple(sorted(p.name for p in changes.iterdir())) if changes.is_dir() else (),
        "road_map.regions": tuple(names_of(served["regions"])),
        "road_map.map_date": str(served["map_date"])[:10] if served.get("known") else None,
        "road_map.change_state": body["change"]["state"],
    }


def files_have(*present: str, absent: tuple[str, ...] = ()) -> Any:
    """Predicate over `queue.files`: the helper's side of the change shows these files and not those."""

    def check(_old: Any, new: Any) -> bool:
        return all(n in new for n in present) and not any(n in new for n in absent)

    check.__name__ = f"queue.files has {present}, not {absent}"
    return check


def delta(world: PlannerWorld, **changed: Any) -> None:
    """Mandate 8: served map and changes folder before and after the When; what is not named is unchanged."""
    rm = state(world)
    assert rm.view_before and rm.view_after, "the scenario captured no view before and after its When"
    assert_state_delta(
        rm.view_before, rm.view_after, RM_UNIVERSE, {k.replace("__", "."): v for k, v in changed.items()}
    )


def when_at(text: str) -> datetime:
    return datetime.strptime(text, "%d %B %Y").replace(tzinfo=UTC)


def tileset_of(text: str) -> str:
    """'27 November' or '27 November 2026' -> the name of the map built that day (the UTC date, D305)."""
    day = datetime.strptime(text if re.search(r"\d{4}", text) else f"{text} 2026", "%d %B %Y")
    return day.strftime("%Y%m%d")


def split_names(text: str) -> list[str]:
    return [part for part in re.split(r", | and ", text) if part]


def key_for(name: str) -> str:
    for feature in catalogue_features():
        if feature["properties"]["name"] == name:
            return key_of(feature)
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")  # a region the catalogue does not hold


def name_of(key: str) -> str:
    return str(feature_by_key(key)["properties"]["name"])


EIGHT_NAMES = [name_of(k) for k in EIGHT]


def keys_of_phrase(what: str) -> list[str]:
    keys: list[str] = []
    for part in re.split(r", | and (?=the |Utah|[A-Z])", what):
        keys.extend(EIGHT if part.strip() == "the eight regions" else [key_for(part.strip())])
    return keys


def clear_volume(rm: RoadMapState) -> None:
    shutil.rmtree(rm.root / "tilesets", ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------- Given
@given(parsers.re(r"today is (?P<date>\d+ \w+ \d{4}) at (?P<hour>\d\d):(?P<minute>\d\d) UTC"))
def given_today_is(world: PlannerWorld, date: str, hour: str, minute: str) -> None:
    world.clock = FakeClock(when_at(date).replace(hour=int(hour), minute=int(minute)))
    rm = state(world)
    rm.clock_set = True
    seen = rm.root / "changes" / "helper-seen"
    if seen.exists():  # the helper looked a moment ago, whatever the day
        stamp = world.clock.now().timestamp()
        os.utime(seen, (stamp, stamp))


@given(
    parsers.re(
        r"the road map was rebuilt from the app and the served map holds (?P<what>.+), with map data of (?P<date>\d+ \w+ \d{4})"  # noqa: E501
    )
)
def given_the_served_map_holds(world: PlannerWorld, what: str, date: str) -> None:
    rm = state(world)
    built = when_at(date).replace(hour=12)
    rm.served, rm.served_name = keys_of_phrase(what), built.strftime("%Y%m%d")
    clear_volume(rm)
    build_volume(rm.root, {rm.served_name: (rm.served, built)})
    world.environ["ROAD_MAP_SERVED_TILESET"] = rm.served_name
    arm(world)
    if world.planner is not None:  # a map switched in under a running planner: the next read sees it
        world.planner.restart()


@given(parsers.re(r"the served map was built on (?P<date>\d+ \w+ \d{4}), before the app kept the regions of a map"))
def given_the_served_map_has_no_regions(world: PlannerWorld, date: str) -> None:
    """Today's map: the tiles of the day and no list of regions (D313 Q1). The map date is then the tiles' date."""
    rm = state(world)
    built = when_at(date).replace(hour=12)
    rm.served_name = built.strftime("%Y%m%d")
    clear_volume(rm)
    base = build_volume(rm.root, {rm.served_name: (list(EIGHT), built)}, with_tar=True)
    folder = base / rm.served_name
    (folder / "road-map.json").unlink(missing_ok=True)
    shutil.rmtree(folder / "outlines", ignore_errors=True)
    use_scripted_engine(world, rm)
    set_engine_epoch(world, rm.served_name)


@given("the Pi holds the maps of 1 November and 27 November, each with its regions")
def given_the_pi_holds_two_maps(world: PlannerWorld) -> None:
    rm = state(world)
    four = [*EIGHT[:4]]
    clear_volume(rm)
    build_volume(
        rm.root,
        {
            "20261101": (four, datetime(2026, 11, 1, 12, tzinfo=UTC)),
            "20261127": (list(EIGHT), datetime(2026, 11, 27, 12, tzinfo=UTC)),
        },
        with_tar=True,
    )
    use_scripted_engine(world, rm)


@given(parsers.re(r"the Pi holds the map of 27 November with (?P<fault>.+)"))
def given_the_pi_holds_a_faulty_map(world: PlannerWorld, fault: str) -> None:
    rm = state(world)
    clear_volume(rm)
    base = build_volume(rm.root, {"20261127": (list(EIGHT), datetime(2026, 11, 27, 12, tzinfo=UTC))}, with_tar=True)
    folder = base / "20261127"
    record = folder / "road-map.json"
    if fault == "no list of regions":
        record.unlink(missing_ok=True)
    elif fault == "a list of regions of a version it does not know":
        record.write_text(json.dumps({"schema": 2, "regions": []}))
    elif fault == "a list of regions cut short":
        record.write_text(record.read_text()[: len(record.read_text()) // 2])
    elif fault == "no place for maps at all":
        shutil.rmtree(base, ignore_errors=True)
    elif fault == "a region border that is not a border":
        (folder / "outlines" / "italy.poly").write_text("this is not a polygon\n")
    else:
        raise AssertionError(f"this world cannot arrange the fault {fault!r}")
    use_scripted_engine(world, rm)


def use_scripted_engine(world: PlannerWorld, rm: RoadMapState) -> None:
    """The planner serves with the real Valhalla adapter against a scripted engine whose /status the scenario sets."""
    rm.engine = ScriptedEngine()
    world.environ["ROUTING_PROVIDER"] = "valhalla"
    world.environ.pop("ROAD_MAP_SERVED_TILESET", None)
    world.routing_transport = httpx.MockTransport(rm.engine)


def set_engine_epoch(world: PlannerWorld, name: str) -> None:
    rm = state(world)
    assert rm.engine is not None, "the scenario did not give the planner a routing engine"
    tar = rm.root / "tilesets" / name / "valhalla_tiles.tar"
    rm.engine.epoch = epoch_of(tar.parent) if tar.exists() else FALLBACK_EPOCH


@given(parsers.re(r"the Pi reports its map data is of (?P<day>\d+ \w+)"))
def given_the_engine_reports_the_map_data(world: PlannerWorld, day: str) -> None:
    set_engine_epoch(world, tileset_of(day))


@given(parsers.re(r"the Pi now serves the map of (?P<day>\d+ \w+), whose regions are the eight and Portugal"))
def given_the_engine_serves_the_new_map(world: PlannerWorld, day: str) -> None:
    rm = state(world)
    name = tileset_of(day)
    built = datetime.strptime(name, "%Y%m%d").replace(hour=2, minute=30, tzinfo=UTC)
    build_volume(rm.root, {name: ([*EIGHT, "portugal"], built)}, with_tar=True)
    set_engine_epoch(world, name)


@given("the Pi is busy building and gives no map date")
def given_the_engine_has_stopped(world: PlannerWorld) -> None:
    rm = state(world)
    assert rm.engine is not None
    rm.engine.mode = "down"


@given("the place where changes are kept cannot be written")
def given_the_changes_folder_is_read_only(world: PlannerWorld) -> None:
    """The place for changes refuses every write, whoever runs the test: a plain file stands in its place."""
    rm = state(world)
    rm.changes_blocked = True
    rm.helper_set = True
    arm(world)


@given("the region service does not answer")
def given_the_region_service_does_not_answer(world: PlannerWorld) -> None:
    rm = arm(world)
    assert rm.region_server is not None
    rm.region_server.stop()


@given(parsers.re(r"the catalogue was fetched (?P<days>\d+) days ago"))
def given_the_catalogue_was_fetched_days_ago(world: PlannerWorld, days: str) -> None:
    """A planner that ran `days` ago and searched once leaves its kept copy in its data folder."""
    rm = arm(world)
    now = world.clock.now()
    world.clock = FakeClock(now - timedelta(days=int(days)))
    world.ensure_planner()
    call(world, "GET", "/api/road-map/catalogue", params={"q": "Utah"})
    assert rm.response is not None and rm.response.status_code == 200, "precondition: the first search did not work"
    assert world.planner is not None
    world.planner.stop()
    world.planner = None
    world.clock = FakeClock(now)


@given("the planner has been restarted")
def given_the_planner_has_been_restarted(world: PlannerWorld) -> None:
    planner(world)
    assert world.planner is not None
    world.planner.restart()


@given(parsers.re(r'(?:Marco|Giulia) is building "(?P<name>[^"]+)"'))
def given_marco_is_building(world: PlannerWorld, name: str) -> None:
    rm = planner(world)
    answer = world.note(world.marco().create_project(name))
    assert answer.status_code == 201, f"precondition failed: could not create {name!r}: {answer.text[:200]}"
    world.project_id, world.project_name = str(answer.json()["id"]), name
    world.before = world.catalog_view()
    rm.items_before = world.before


@given("Marco has created a project and added a place to it")
def given_marco_has_a_project_with_a_place(world: PlannerWorld) -> None:
    planner(world)
    created = world.note(world.marco().create_project("Assietta weekend"))
    assert created.status_code == 201, created.text[:200]
    placed = world.marco().add_poi(str(created.json()["id"]), "Colle dell'Assietta", 45.0, 7.0)
    assert placed.status_code in (200, 201), placed.text[:200]


@given("Marco has asked the planner what road map it serves")
def given_marco_has_asked(world: PlannerWorld) -> None:
    road_map(world)


@given(parsers.re(r"a new map of (?P<day>\d+ \w+) was left behind by a switch that failed"))
def given_a_map_was_left_behind(world: PlannerWorld, day: str) -> None:
    folder = state(world).root / "tilesets" / tileset_of(day)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "valhalla_tiles.tar").write_text("half switched\n")


# -- the change (a Given when it is already pending, a When when the owner does it now)
CHANGE = (
    r"the owner (?:has planned|plans) the change adding (?P<added>[A-Za-z' -]+?)"
    r"(?: and removing (?P<removed>[A-Za-z-]+))?"
    r"(?P<when> for tonight at 02:00| to start now| to start \d+ (?:minutes?|days?) from now)?"
)


def start_at_of(world: PlannerWorld, text: str | None) -> str | None:
    now = world.clock.now()
    if not text or text.strip() == "to start now":
        return None
    if "tonight" in text:
        due = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    else:
        found = re.search(r"(\d+) (minute|day)", text)
        assert found is not None, text
        number, unit = found.groups()
        due = now + (timedelta(minutes=int(number)) if unit == "minute" else timedelta(days=int(number)))
    return due.strftime("%Y-%m-%dT%H:%M:%SZ")


def change_body(world: PlannerWorld, added: str | None, removed: str | None, when_text: str | None) -> dict[str, Any]:
    rm = state(world)
    keys = [k for k in rm.served if not (removed and k == key_for(removed))]
    if added and key_for(added) not in keys:
        keys.append(key_for(added))
    return {"region_keys": keys, "start_at": start_at_of(world, when_text)}


def plan_change(world: PlannerWorld, added: str, removed: str | None, when_text: str | None) -> None:
    rm = planner(world)
    rm.view_before = rm_view(world)
    call(world, "POST", "/api/road-map/change", json=change_body(world, added, removed, when_text))
    rm.view_after = rm_view(world)


@given(parsers.re(CHANGE))
def given_the_owner_has_planned(world: PlannerWorld, added: str, removed: str | None, when: str | None) -> None:
    plan_change(world, added, removed, when)
    response = state(world).response
    assert response is not None and response.status_code == 201, (
        f"precondition failed: the change was not planned: {response and response.text[:200]}"
    )


@when(parsers.re(CHANGE))
def when_the_owner_plans(world: PlannerWorld, added: str, removed: str | None, when: str | None) -> None:
    plan_change(world, added, removed, when)


@when(parsers.re(r"the owner asks what adding (?P<added>[A-Za-z' -]+) would cost"))
def when_the_owner_asks_the_cost(world: PlannerWorld, added: str) -> None:
    rm = planner(world)
    rm.view_before = rm_view(world)
    call(world, "POST", "/api/road-map/change/preview", json=change_body(world, added, None, None))
    rm.view_after = rm_view(world)


@when("the owner asks what refreshing the map data would cost")
def when_the_owner_asks_the_refresh_cost(world: PlannerWorld) -> None:
    rm = planner(world)
    rm.view_before = rm_view(world)
    call(world, "POST", "/api/road-map/change/preview", json=change_body(world, None, None, None))
    rm.view_after = rm_view(world)
    assert rm.response is not None


@when("the owner cancels it")
def when_the_owner_cancels_it(world: PlannerWorld) -> None:
    rm = planner(world)
    rm.view_before = rm_view(world)
    call(world, "DELETE", "/api/road-map/change")
    rm.view_after = rm_view(world)


@given("the helper has taken it")
def given_the_helper_has_taken_it(world: PlannerWorld) -> None:
    """What the helper does first: rename the pending request to the running one (atomic, as D303)."""
    changes = state(world).root / "changes"
    (changes / "request.txt").rename(changes / "running.txt")


# -- what the helper writes while it works (US-30)
def helper_writes(world: PlannerWorld, step: str, step_at: str | None = None) -> None:
    rm = state(world)
    changes = rm.root / "changes"
    plan_change(world, "Portugal", None, " to start now")
    assert rm.response is not None and rm.response.status_code == 201, f"precondition: {rm.response.text[:200]}"
    (changes / "request.txt").rename(changes / "running.txt")
    stamp = step_at or str(int(world.clock.now().timestamp()))
    (changes / "progress.txt").write_text(f"step={step}\nstep_at={stamp}\nserving={rm.served_name}\n")


@given(parsers.re(r"the helper has started a rebuild adding Portugal and is (?P<step>\w+)"))
def given_the_helper_has_started(world: PlannerWorld, step: str) -> None:
    helper_writes(world, step)


@given(parsers.re(r"the rebuild step began at (?P<hour>\d\d):(?P<minute>\d\d) UTC"))
def given_the_step_began_at(world: PlannerWorld, hour: str, minute: str) -> None:
    progress = state(world).root / "changes" / "progress.txt"
    day = world.clock.now().replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    lines = [
        f"step_at={int(day.timestamp())}" if line.startswith("step_at=") else line
        for line in progress.read_text().splitlines()
    ]
    progress.write_text("\n".join(lines) + "\n")


def helper_ends(world: PlannerWorld, result: str) -> None:
    rm = state(world)
    helper_writes(world, "switching")
    changes = rm.root / "changes"
    request = (changes / "running.txt").read_text()
    (changes / "running.txt").unlink()
    finished = int(world.clock.now().timestamp())
    (changes / "result.txt").write_text(request + f"finished_at={finished}\n{result}")


@given(parsers.re(r"a rebuild adding Portugal ended well, making the map of (?P<day>\d+ \w+)"))
def given_a_rebuild_ended_well(world: PlannerWorld, day: str) -> None:
    helper_ends(world, f"state=done\ntileset={tileset_of(day)}\n")


@given(parsers.re(r"a rebuild adding Portugal ended because (?P<reason>.+)"))
def given_a_rebuild_ended_because(world: PlannerWorld, reason: str) -> None:
    space = re.fullmatch(r"the disk had (\d+) GB free and needed (\d+) GB", reason)
    if space:
        helper_ends(world, f"state=failed\ncode=disk\nfree_gb={space.group(1)}\nneed_gb={space.group(2)}\n")
        return
    assert reason in FAILURES, f"this world does not know the failure {reason!r}"
    helper_ends(world, f"state=failed\ncode={FAILURES[reason]}\nfree_gb=18\nneed_gb=25\nhave_gb=9\n")


@given(parsers.re(r"the helper last looked (?P<minutes>\d+) minutes ago"))
def given_the_helper_last_looked(world: PlannerWorld, minutes: str) -> None:
    rm = state(world)
    seen = rm.root / "changes" / "helper-seen"
    seen.touch()
    stamp = (world.clock.now() - timedelta(minutes=int(minutes))).timestamp()
    os.utime(seen, (stamp, stamp))
    rm.helper_set = True


@given("the helper has never run on the Pi")
def given_the_helper_has_never_run(world: PlannerWorld) -> None:
    rm = state(world)
    (rm.root / "changes").mkdir(parents=True, exist_ok=True)
    (rm.root / "changes" / "helper-seen").unlink(missing_ok=True)
    rm.helper_set = True


# --------------------------------------------------------------------------------------------------- the catalogue
@given(parsers.re(r'the owner has searched the catalogue for "(?P<words>[^"]*)"'))
@when(parsers.re(r'the owner searches the catalogue for "(?P<words>[^"]*)"'))
def when_the_owner_searches_the_catalogue(world: PlannerWorld, words: str) -> None:
    call(world, "GET", "/api/road-map/catalogue", params={"q": words})


@when(parsers.re(r'(?P<days>\d+) days pass and the owner searches the catalogue for "(?P<words>[^"]*)"'))
def when_days_pass_and_the_owner_searches(world: PlannerWorld, days: str, words: str) -> None:
    assert isinstance(world.clock, FakeClock)
    world.clock.advance(int(days) * 86_400)
    call(world, "GET", "/api/road-map/catalogue", params={"q": words})


def found(world: PlannerWorld) -> list[dict[str, Any]]:
    rm = state(world)
    assert rm.response is not None and rm.response.status_code == 200, (
        f"the catalogue did not answer: {rm.response.status_code if rm.response else None}"
    )
    body = rm.response.json()
    rows: list[dict[str, Any]] = body["results"] if isinstance(body, dict) else body
    return rows


@then(
    parsers.re(
        r'the answer holds "(?P<name>[^"]+)", part of "(?P<parent>[^"]+)", of (?P<size>[\d.]+) GB, (?P<mark>not yet in the map|already in the map)'  # noqa: E501
    )
)
def then_the_answer_holds_the_region(world: PlannerWorld, name: str, parent: str, size: str, mark: str) -> None:
    row = only([r for r in found(world) if r["name"] == name], f"catalogue answers named {name!r}")
    assert row["parent_name"] == parent, row
    assert abs(row["bytes"] - float(size) * GB) < 0.05 * GB, row
    assert row["in_map"] is (mark == "already in the map"), row  # PIN: the mark is `in_map`


@then(parsers.re(r'the answer holds "(?P<name>[^"]+)"$'))
def then_the_answer_holds_the_name(world: PlannerWorld, name: str) -> None:
    assert name in [r["name"] for r in found(world)], f"the catalogue answer lacks {name!r}"


@then(
    parsers.re(
        r'the answer holds two regions named "(?P<name>[^"]+)", one part of "(?P<first>[^"]+)" and one part of "(?P<second>[^"]+)"'  # noqa: E501
    )
)
def then_two_regions_share_the_name(world: PlannerWorld, name: str, first: str, second: str) -> None:
    parents = sorted(r["parent_name"] for r in found(world) if r["name"] == name)
    assert parents == sorted([first, second]), f"the {name!r} regions are part of {parents}"


@then("the planner refuses the search and says the name is too short")
def then_the_search_is_refused_as_too_short(world: PlannerWorld) -> None:
    response = state(world).response
    assert response is not None and response.status_code == 422, (
        f"the search answered {response and response.status_code}"
    )
    message = str(response.json().get("message", "")).lower()
    assert "short" in message or "two" in message or "2" in message, message


# ------------------------------------------------------------------------------------------ the road map and change
@when("Marco asks the planner what road map it serves")
def when_marco_asks_the_road_map(world: PlannerWorld) -> None:
    rm = planner(world)
    rm.view_before = rm_view(world)
    if world.project_id is not None:
        call(world, "GET", f"/api/projects/{world.project_id}/coverage")


def served_of(world: PlannerWorld) -> dict[str, Any]:
    return dict(road_map(world)["served"])


@then(parsers.re(r"the planner names (?P<names>Italy, .+)"))
def then_the_planner_names(world: PlannerWorld, names: str) -> None:
    wanted = split_names(names)
    got = names_of(served_of(world)["regions"])
    assert got == wanted, f"the planner names {got}, not {wanted}"


@then(parsers.re(r"the planner names the regions of the map of (?P<day>\d+ \w+) and its map date"))
def then_the_planner_names_the_map(world: PlannerWorld, day: str) -> None:
    served = served_of(world)
    name = tileset_of(day)
    expected = [name_of(k) for k in EIGHT[:4]] if name == "20261101" else EIGHT_NAMES
    assert names_of(served["regions"]) == expected, names_of(served["regions"])
    assert str(served["map_date"])[:10] == f"{name[:4]}-{name[4:6]}-{name[6:]}", served["map_date"]


@then(parsers.re(r"the planner names the nine regions and the map date of the map of (?P<day>\d+ \w+)"))
def then_the_planner_names_the_nine(world: PlannerWorld, day: str) -> None:
    served = served_of(world)
    name = tileset_of(day)
    assert names_of(served["regions"]) == [*EIGHT_NAMES, "Portugal"], served["regions"]
    assert str(served["map_date"])[:10] == f"{name[:4]}-{name[4:6]}-{name[6:]}", served["map_date"]


@then(parsers.re(r"the map data is dated (?P<date>\d+ \w+ \d{4}) and the regions total (?P<gb>[\d.]+) GB"))
def then_the_map_is_dated(world: PlannerWorld, date: str, gb: str) -> None:
    served = served_of(world)
    assert str(served["map_date"])[:10] == when_at(date).strftime("%Y-%m-%d"), served["map_date"]
    assert abs(served["total_bytes"] - float(gb) * GB) < 0.05 * GB, served["total_bytes"]


@then(parsers.re(r"the map data is still dated (?P<date>\d+ \w+ \d{4})"))
def then_the_map_is_still_dated(world: PlannerWorld, date: str) -> None:
    assert str(served_of(world)["map_date"])[:10] == when_at(date).strftime("%Y-%m-%d")


@then("no change is pending")
@then("nothing is pending")
def then_nothing_is_pending(world: PlannerWorld) -> None:
    assert road_map(world)["change"]["state"] == "none"


@then("nothing is pending and the regions served are still the eight")
def then_nothing_is_pending_and_the_eight_stay(world: PlannerWorld) -> None:
    rm = state(world)
    delta(world, road_map__change_state=set_to("none"), queue__files=files_have(absent=("request.txt",)))
    assert list(rm.view_after["road_map.regions"]) == EIGHT_NAMES


@then("the helper is no longer given the change")
def then_the_helper_has_no_change(world: PlannerWorld) -> None:
    delta(
        world, road_map__change_state=set_to("none"), queue__files=files_have("cancelled.txt", absent=("request.txt",))
    )
    changes = state(world).root / "changes"  # adapter-integration: the files are the helper's side of the port
    assert not (changes / "request.txt").exists() and (changes / "cancelled.txt").exists()


@then("the regions served are still the eight")
def then_the_regions_are_still_the_eight(world: PlannerWorld) -> None:
    assert names_of(served_of(world)["regions"]) == EIGHT_NAMES


@then(
    parsers.re(
        r"the summary says (?P<gb>[\d.]+) GB to download, planning paused about (?P<pause>\d+) minutes and the rebuild about (?P<total>\d+) minutes"  # noqa: E501
    )
)
def then_the_summary_says(world: PlannerWorld, gb: str, pause: str, total: str) -> None:
    response = state(world).response
    assert response is not None and response.status_code in (200, 201), (
        f"no summary: {response and response.status_code}"
    )
    delta(world)  # a summary writes nothing and changes nothing the owner sees
    summary = response.json()
    assert abs(summary["total_bytes"] - float(gb) * GB) < 0.05 * GB, summary["total_bytes"]  # PIN
    assert summary["estimate"]["pause_minutes"] == int(pause), summary["estimate"]
    assert summary["estimate"]["total_minutes"] == int(total), summary["estimate"]


@then("the summary adds and removes no region")
def then_the_summary_changes_nothing(world: PlannerWorld) -> None:
    response = state(world).response
    assert response is not None and response.status_code in (200, 201), response and response.status_code
    delta(world)
    summary = response.json()
    assert summary["added"] == [] and summary["removed"] == [], summary


@then("the summary says Utah is not linked by land to the other regions")
def then_the_summary_says_utah_is_apart(world: PlannerWorld) -> None:
    response = state(world).response
    assert response is not None and response.status_code in (200, 201), response and response.status_code
    summary = response.json()
    assert "Utah" in str(summary.get("not_linked_note")), summary  # PIN: `not_linked_note`
    assert len(summary["land_groups"]) == 2, summary  # PIN: `land_groups`


@then("the change can still be applied")
def then_the_change_can_be_applied(world: PlannerWorld) -> None:
    response = state(world).response
    assert response is not None and response.status_code in (200, 201), response and response.status_code


@then(
    parsers.re(
        r"the change is pending, to be started on (?P<date>\d+ \w+ \d{4}) at (?P<hour>\d\d):(?P<minute>\d\d) UTC, adding (?P<added>\w+) and removing nothing"  # noqa: E501
    )
)
def then_the_change_is_pending(world: PlannerWorld, date: str, hour: str, minute: str, added: str) -> None:
    rm = state(world)
    assert rm.response is not None and rm.response.status_code == 201, rm.response and rm.response.text[:200]
    change = road_map(world)["change"]
    assert change["state"] == "planned", change
    assert str(change["start_at"]).startswith(f"{when_at(date):%Y-%m-%d}T{hour}:{minute}"), change["start_at"]
    assert names_of(change["added"]) == [added] and change["removed"] == [], change
    delta(world, road_map__change_state=set_to("planned"), queue__files=files_have("request.txt"))


@then(parsers.re(r"the planner refuses it, because (?P<reason>.+)"))
def then_the_planner_refuses_it(world: PlannerWorld, reason: str) -> None:
    assert reason in REFUSALS, f"this world does not know the refusal reason {reason!r}"
    code, words = REFUSALS[reason]
    response = state(world).response
    assert response is not None and response.status_code in (409, 422, 503), (
        f"the planner did not refuse: {response and response.status_code}"
    )
    if code == "rebuilds_not_set_up":
        assert response.status_code == 503, f"the refusal is {response.status_code}, not 503"
    delta(world)  # nothing is written and nothing changes
    body = response.json()
    if code is not None:
        assert body.get("code") == code, f"the refusal is {body.get('code')!r}, not {code!r}"
    for word in words:
        assert word in str(body.get("message")), f"the refusal does not say {word!r}: {body.get('message')!r}"


@then("the planner refuses saying the rebuild has already started")
def then_the_cancel_is_refused(world: PlannerWorld) -> None:
    response = state(world).response
    assert response is not None and response.status_code == 409, (
        f"the cancel answered {response and response.status_code}"
    )
    delta(world)


@then(parsers.re(r"it names (?P<date>\d+ \w+ \d{4}) as the next day a rebuild may run"))
def then_it_names_the_next_day(world: PlannerWorld, date: str) -> None:
    response = state(world).response
    assert response is not None, "the planner was not asked"
    body = response.json()
    assert str(body.get("next_rebuild_from", ""))[:10] == when_at(date).strftime("%Y-%m-%d"), body


@then("the planner keeps it pending")
def then_the_planner_keeps_it_pending(world: PlannerWorld) -> None:
    response = state(world).response
    assert response is not None and response.status_code == 201, (
        f"the change was not kept: {response and response.text[:200]}"
    )
    delta(world, road_map__change_state=set_to("planned"), queue__files=files_have("request.txt"))
    assert road_map(world)["change"]["state"] == "planned"


@then("the pending change still adds Portugal only")
def then_the_pending_change_is_unchanged(world: PlannerWorld) -> None:
    assert names_of(road_map(world)["change"]["added"]) == ["Portugal"]


@then("the planner says changing the road map is not available right now")
def then_changes_are_not_available(world: PlannerWorld) -> None:
    assert road_map(world)["limits"]["changes_available"] is False


@then("the regions are still named")
def then_the_regions_are_still_named(world: PlannerWorld) -> None:
    assert names_of(served_of(world)["regions"]) == EIGHT_NAMES


@then(
    parsers.re(
        r"the planner's health names the (?P<what>road map changes|road map|region catalogue) as (?P<how>unavailable|unreadable)"  # noqa: E501
    )
)
def then_the_health_names(world: PlannerWorld, what: str, how: str) -> None:
    reason = {
        "road map changes": "road_map_changes_unavailable",
        "road map": "road_map_unreadable",
        "region catalogue": "region_catalogue_unavailable",
    }[what]
    text = world.marco().health_detail().text
    assert reason in text, f"the health detail does not name {reason}: {text[:300]}"


@then("the planner does not report the catalogue as unavailable")
def then_the_health_does_not_name_the_catalogue(world: PlannerWorld) -> None:
    assert "region_catalogue_unavailable" not in world.marco().health_detail().text


@then("the planner says the map coverage is unknown and names no region")
def then_the_coverage_is_unknown(world: PlannerWorld) -> None:
    served = served_of(world)
    assert served["known"] is False and served["regions"] == [], served


@then("the planner still works")
def then_the_planner_still_answers(world: PlannerWorld) -> None:
    assert world.marco().health().status_code == 200


# --------------------------------------------------------------------------------- the region service (real client)
def region_requests(world: PlannerWorld, path_contains: str = "", method: str | None = None) -> list[Any]:
    rm = state(world)
    assert rm.region_server is not None
    return rm.region_server.requests(method, path_contains)


def list_fetches(world: PlannerWorld) -> list[Any]:
    asked = region_requests(world, "index-v1")
    assert all(a.headers.get("user-agent", "").startswith("overland-planner/") for a in asked if asked), asked[
        0
    ].headers
    return asked


@then("the catalogue was fetched by a client that names itself as the planner")
def then_the_catalogue_was_fetched(world: PlannerWorld) -> None:
    assert len(list_fetches(world)) == 1, f"the list was fetched {len(list_fetches(world))} times"


@then("the catalogue was not fetched again")
def then_the_catalogue_was_not_fetched_again(world: PlannerWorld) -> None:
    assert len(list_fetches(world)) == 1, f"the list was fetched {len(list_fetches(world))} times, not once"


@then("the catalogue was fetched again")
def then_the_catalogue_was_fetched_again(world: PlannerWorld) -> None:
    assert len(list_fetches(world)) == 2, f"the list was fetched {len(list_fetches(world))} times, not twice"


@given(parsers.re(r"(?P<days>\d+) days have passed"))
def given_days_have_passed(world: PlannerWorld, days: str) -> None:
    assert isinstance(world.clock, FakeClock)
    world.clock.advance(int(days) * 86_400)


@then("only the regions of the answers were asked about, never a project, a trail or a place")
def then_only_regions_were_asked_about(world: PlannerWorld) -> None:
    for seen in region_requests(world):
        assert not seen.query, f"the region service was sent {seen.query}"
        assert seen.path.endswith(("index-v1-nogeom.json", ".poly", "-latest.osm.pbf")), seen.path
    sized = {s.path.split("/")[-2] for s in region_requests(world, "-latest.osm.pbf", "HEAD")}
    assert sized <= {"utah", "italy"}, f"sizes were asked for {sized}"
    assert region_requests(world, ".poly") == [], "a border was fetched for a region that was only searched"


@then("the size of Utah was not asked again")
def then_the_size_was_asked_once(world: PlannerWorld) -> None:
    asked = region_requests(world, "utah-latest.osm.pbf", "HEAD")
    assert len(asked) == 1, f"the size of Utah was asked {len(asked)} times"


@then("the border of Portugal was fetched, and no other border")
def then_the_border_was_fetched_once(world: PlannerWorld) -> None:
    borders = [s.path for s in region_requests(world, ".poly", "GET")]
    assert borders and all(p.endswith("portugal.poly") for p in borders), f"borders fetched: {borders}"
    assert len(borders) == 1, f"the border of Portugal was fetched {len(borders)} times"


# --------------------------------------------------------------------------------------------- the pending change
@then(
    "the planner keeps the change ready for the helper, with the eight regions of the new map, the start time and what is added and removed"  # noqa: E501
)
def then_the_change_is_stored(world: PlannerWorld) -> None:
    text = (state(world).root / "changes" / "request.txt").read_text()  # adapter-integration: the helper's input
    lines = text.splitlines()
    assert lines and lines[0] == "schema=1", lines[:2]
    regions = [line.split("=", 1)[1].split("\t") for line in lines if line.startswith("region=")]
    assert len(regions) == 8 and all(len(r) == 6 for r in regions), regions  # key, name, parent, pbf, poly, bytes
    names = [r[1] for r in regions]
    assert "Portugal" in names and "Austria" not in names, names
    assert all(r[3].endswith("-latest.osm.pbf") and r[4].endswith(".poly") for r in regions), regions
    due = int(datetime(2026, 11, 29, 2, 0, tzinfo=UTC).timestamp())
    assert f"start_at={due}" in lines, f"the start time must be UTC epoch seconds ({due}): {lines[:4]}"
    assert any(line.startswith("added=") and "Portugal" in line for line in lines), lines
    assert any(line.startswith("removed=") and "Austria" in line for line in lines), lines


@then("the planner leaves the list of the map's regions to the rebuild")
def then_the_planner_wrote_no_record(world: PlannerWorld) -> None:
    changes = state(world).root / "changes"
    assert (changes / "request.txt").exists() and not (changes / "record.json").exists(), sorted(
        p.name for p in changes.iterdir()
    )


# ------------------------------------------------------------------------------------------------- US-30 the change
def change_of(world: PlannerWorld) -> dict[str, Any]:
    change: dict[str, Any] = road_map(world)["change"]
    return change


@then(parsers.re(r'the change is running and its step is "(?P<step>\w+)"'))
def then_the_change_is_running(world: PlannerWorld, step: str) -> None:
    change = change_of(world)
    assert (change["state"], change["step"]) == ("running", step), change


@then(
    parsers.re(
        r"planning is (?P<state>not paused|paused, back about (?P<minutes>\d+) minutes after (?P<hour>\d\d):(?P<minute>\d\d))"  # noqa: E501
    )
)
def then_planning_is(
    world: PlannerWorld, state: str, minutes: str | None, hour: str | None, minute: str | None
) -> None:
    body = road_map(world)
    if state == "not paused":
        assert body["planning_paused"] is False, body
        return
    assert body["planning_paused"] is True, body
    back = datetime.fromisoformat(str(body["planning_back_at"]).replace("Z", "+00:00"))
    began = back.replace(hour=int(hour or 0), minute=int(minute or 0), second=0, microsecond=0)
    assert abs((back - began).total_seconds() / 60 - int(minutes or 0)) <= 1, f"planning is back at {back}"


@then("the change has failed and says not enough space on the disk, 18 GB free and 25 GB needed")
def then_the_change_failed_for_space(world: PlannerWorld) -> None:
    change = change_of(world)
    message = str(change["result"]["message"])
    assert change["state"] == "failed" and "disk" in message and "18 GB" in message and "25 GB" in message, change


@then("the change is kept")
def then_the_change_is_kept(world: PlannerWorld) -> None:
    assert names_of(change_of(world)["added"]) == ["Portugal"], change_of(world)


@then("the change has failed and the words shown hold no code name")
def then_the_change_failed_in_plain_words(world: PlannerWorld) -> None:
    change = change_of(world)
    message = str(change["result"]["message"])
    code = str(change["result"]["code"])
    assert change["state"] == "failed" and message.strip(), change
    assert code not in message and "_" not in message, f"the words show a code: {message!r}"


@then("the change is done")
def then_the_change_is_done(world: PlannerWorld) -> None:
    assert change_of(world)["state"] == "done"


@then("the planner says rebuilds are not set up on the Pi")
def then_rebuilds_are_not_set_up(world: PlannerWorld) -> None:
    body = road_map(world)
    assert body["change"]["state"] == "planned" and body["limits"]["helper_seen"] is False, body


# ------------------------------------------------------------------------------------------------ US-28 the coverage
@given(parsers.re(r'Marco has added the place "(?P<name>[^"]+)" at (?P<lat>-?[\d.]+), (?P<lon>-?[\d.]+)'))
@when(parsers.re(r'Marco adds the place "(?P<name>[^"]+)" at (?P<lat>-?[\d.]+), (?P<lon>-?[\d.]+)'))
def when_marco_adds_a_place(world: PlannerWorld, name: str, lat: str, lon: str) -> None:
    rm = planner(world)
    assert world.project_id is not None, "no project is open"
    world.scratch["trip_before"] = world.catalog_view()
    answer = call(
        world,
        "POST",
        f"/api/projects/{world.project_id}/pois",
        json={"name": name, "lat": float(lat), "lon": float(lon)},
    )
    rm.last_item_id = str(answer.json().get("id")) if answer.status_code in (200, 201) else None
    rm.last_item_name = name
    world.scratch["trip_after"] = world.catalog_view()


@when(parsers.re(r"Marco adds a trail from (?P<entry>\w+) through (?P<middle>\w+) to (?P<exit>\w+)"))
def when_marco_adds_a_trail(world: PlannerWorld, entry: str, middle: str, exit: str) -> None:
    rm = planner(world)
    assert world.project_id is not None, "no project is open"
    name = f"{entry}-{exit}".lower()
    world.scratch["trip_before"] = world.catalog_view()
    file = gpx_of(name, [PLACES_AT[entry], PLACES_AT[middle], PLACES_AT[exit]])
    rm.response = world.note(world.marco().import_track_files(world.project_id, [(f"{name}.gpx", file)]))
    rm.last_item_name = name
    rm.last_item_id = next((str(i["id"]) for i in world.items() if i["name"] == name), None)
    world.scratch["trip_after"] = world.catalog_view()


def trip_gained_one(world: PlannerWorld) -> None:
    """Mandate 8 on the trip: the item list gained exactly one row, the project list did not change."""
    before, after = world.scratch["trip_before"], world.scratch["trip_after"]
    assert_state_delta(
        before,
        after,
        CATALOG_UNIVERSE,
        {
            "project.items": lambda old, new: len(new) - len(old) == 1 and set(old) <= set(new),
            "projects.names": unchanged(),
        },
    )


def coverage_of(world: PlannerWorld) -> dict[str, Any]:
    assert world.project_id is not None
    answer = call(world, "GET", f"/api/projects/{world.project_id}/coverage")
    assert answer.status_code == 200, f"the trip's coverage did not open: {answer.status_code} {answer.text[:200]}"
    body: dict[str, Any] = answer.json()
    return body


def item_is_kept(world: PlannerWorld) -> None:
    rm = state(world)
    trip_gained_one(world)
    assert rm.last_item_id is not None, (
        f"the planner did not keep {rm.last_item_name!r}: {rm.response and rm.response.text[:200]}"
    )
    assert rm.last_item_name.lower() in [str(i["name"]).lower() for i in world.items()]


@then(parsers.re(r"the (?:place|trail) is kept and is (?P<verdict>inside|outside) the road map"))
def then_the_item_is_kept_inside_or_outside(world: PlannerWorld, verdict: str) -> None:
    item_is_kept(world)
    coverage = coverage_of(world)
    assert coverage["known"] is True, f"the coverage is unknown: {coverage}"
    assert (state(world).last_item_id in coverage["outside_item_ids"]) == (verdict == "outside"), coverage


@then(parsers.re(r'the place "(?P<name>[^"]+)" is kept and is outside the road map'))
def then_the_named_place_is_kept_and_outside(world: PlannerWorld, name: str) -> None:
    trip_gained_one(world)
    item = next((i for i in world.items() if i["name"] == name), None)
    assert item is not None, f"{name!r} is not in the trip"
    assert str(item["id"]) in coverage_of(world)["outside_item_ids"]


@then("the place is kept and the trip's coverage is unknown with no place named as outside")
def then_the_trip_coverage_is_unknown(world: PlannerWorld) -> None:
    item_is_kept(world)
    coverage = coverage_of(world)
    assert coverage["known"] is False and coverage["outside_item_ids"] == [], coverage


@then(parsers.re(r"the trip's stops are in (?P<count>one|two) groups? of regions (?:that are not )?linked by land"))
def then_the_stops_are_in_groups(world: PlannerWorld, count: str) -> None:
    groups = coverage_of(world)["groups"]
    assert len(groups) == {"one": 1, "two": 2}[count], groups


@then(parsers.re(r"one group holds (?P<first>\w+) and the other holds (?P<second>\w+)"))
def then_each_group_holds_one_stop(world: PlannerWorld, first: str, second: str) -> None:
    by_id = {str(i["id"]): i["name"] for i in world.items()}
    held = sorted(sorted(by_id[i] for i in g["item_ids"]) for g in coverage_of(world)["groups"])
    assert held == sorted([[first], [second]]), held


@when("Marco opens the map settings")
def when_marco_opens_the_map_settings(world: PlannerWorld) -> None:
    planner(world)
    answer = world.note(world.marco().map_config())
    assert answer.status_code == 200, f"the map settings did not open: {answer.status_code} {answer.text[:300]}"
    world.scratch["map_config"] = answer.json()


@then("the map settings hold no road-map area")
def then_no_road_map_area(world: PlannerWorld) -> None:
    assert "road_map_area" not in world.scratch["map_config"], world.scratch["map_config"]


@then(parsers.re(r"the map settings say place search is (?P<offer>offered|not offered)"))
def then_place_search_is_offered(world: PlannerWorld, offer: str) -> None:
    assert world.scratch["map_config"].get("place_search") is (offer == "offered"), world.scratch["map_config"]


# ------------------------------------------------------------------------------------------------ US-29 place search
@given(parsers.re(r"place search is switched on and answers (?P<what>.+)"))
def given_place_search_is_on(world: PlannerWorld, what: str) -> None:
    rm = state(world)
    rm.place_on, rm.place_off = True, False
    world.clock = RealClock()  # type: ignore[assignment]
    rm.clock_set = True
    arm(world)


@given(
    parsers.re(
        r"place search is switched on and the search service (?P<fault>answers that it is busy|is not running|answers an error|answers nonsense)"  # noqa: E501
    )
)
def given_the_place_service_is_faulty(world: PlannerWorld, fault: str) -> None:
    rm = state(world)
    rm.place_mode = {
        "answers that it is busy": "busy",
        "is not running": "healthy",
        "answers an error": "error",
        "answers nonsense": "nonsense",
    }[fault]
    world.clock = RealClock()  # type: ignore[assignment]
    rm.clock_set = True
    arm(world)
    if fault == "is not running":
        assert rm.place_server is not None
        rm.place_server.stop()


@given("place search is switched off")
def given_place_search_is_off(world: PlannerWorld) -> None:
    rm = state(world)
    rm.place_off = True
    arm(world)


@given("place search is switched on with its address left empty")
def given_the_search_address_is_empty(world: PlannerWorld) -> None:
    rm = state(world)
    rm.place_url_empty = (
        True  # no fake server: an empty address means the usual address, which this scenario never calls
    )
    arm(world)
    world.environ["PLACE_SEARCH_URL"] = ""


@given(parsers.re(r'(?:Marco|Giulia) has searched for the place "(?P<words>[^"]*)"'))
@when(parsers.re(r'Marco searches for the place "(?P<words>[^"]*)"'))
def when_marco_searches_for_the_place(world: PlannerWorld, words: str) -> None:
    call(world, "GET", "/api/places/search", params={"q": words})


@when(parsers.re(r'Marco presses search for "(?P<words>[^"]+)" twice at once'))
def when_marco_presses_twice(world: PlannerWorld, words: str) -> None:
    rm = planner(world)
    session = world.marco()
    with ThreadPoolExecutor(2) as pool:
        rm.answers = list(pool.map(lambda _: session.call("GET", "/api/places/search", params={"q": words}), range(2)))
    rm.response = rm.answers[-1]


@when(parsers.re(r"Giulia adds the one in (?P<country>\w+)"))
def when_giulia_adds_the_result(world: PlannerWorld, country: str) -> None:
    rm = state(world)
    assert rm.response is not None and rm.response.status_code == 200, rm.response and rm.response.text[:200]
    chosen = next((r for r in rm.response.json() if r["country"] == country), None)
    assert chosen is not None, f"the search found no place in {country}: {rm.response.json()}"
    assert world.project_id is not None
    world.scratch["trip_before"] = world.catalog_view()
    world.note(world.marco().add_poi(world.project_id, chosen["name"], chosen["lat"], chosen["lon"]))
    world.scratch["trip_after"] = world.catalog_view()


def place_server(world: PlannerWorld) -> RecordingServer:
    rm = state(world)
    assert rm.place_server is not None, "this scenario has no place search service"
    return rm.place_server


def place_answers(world: PlannerWorld) -> list[dict[str, Any]]:
    response = state(world).response
    assert response is not None and response.status_code == 200, (
        f"the search answered {response and response.status_code}"
    )
    rows: list[dict[str, Any]] = response.json()
    return rows


@then(
    parsers.re(
        r'the answer holds "(?P<name>[^"]+)" in (?P<region>[^,]+), (?P<country>\w+), with its latitude and longitude'
    )
)
def then_the_place_answer(world: PlannerWorld, name: str, region: str, country: str) -> None:
    row = place_answers(world)[0]
    assert (row["name"], row["region"], row["country"]) == (name, region, country), row
    assert abs(row["lat"] - 43.75) < 0.01 and abs(row["lon"] - 6.33) < 0.01, row


@then("the answer holds no place")
def then_the_answer_holds_no_place(world: PlannerWorld) -> None:
    assert place_answers(world) == []


@then("both answers hold the same place")
def then_both_answers_agree(world: PlannerWorld) -> None:
    first, second = last_two(state(world).answers, "answers")
    assert first.status_code == second.status_code == 200 and first.json() == second.json() != [], (
        first.text,
        second.text,
    )


@then("the search service was asked for a short list of places, each with its region")
def then_the_query_shape(world: PlannerWorld) -> None:
    seen = only(place_server(world).requests("GET", "/search"), "requests the search service saw")
    assert seen.query.get("limit") == ["5"] and seen.query.get("addressdetails") == ["1"], seen.query
    assert seen.query.get("format") == ["jsonv2"], seen.query


@then("the search service saw a client that names itself as the planner")
def then_the_client_names_itself(world: PlannerWorld) -> None:
    seen = only(place_server(world).requests("GET", "/search"), "requests the search service saw")
    assert seen.headers.get("user-agent", "").startswith("overland-planner/"), seen.headers


@then("the search service received no contact detail")
def then_no_contact_detail(world: PlannerWorld) -> None:
    seen = only(place_server(world).requests("GET", "/search"), "requests the search service saw")
    assert "email" not in seen.query and "contact" not in seen.query, seen.query


@then("the search service has seen no request")
def then_the_service_saw_nothing(world: PlannerWorld) -> None:
    assert place_server(world).requests() == []


@then("the search service saw one request")
def then_the_service_saw_one(world: PlannerWorld) -> None:
    assert len(place_server(world).requests("GET", "/search")) == 1


@then("the search service was not asked twice within a second")
def then_the_requests_are_a_second_apart(world: PlannerWorld) -> None:
    first, second = last_two(place_server(world).requests("GET", "/search"), "requests the search service saw")
    assert second.at - first.at >= 0.95, f"the requests were {second.at - first.at:.2f} s apart"


@then("the search service received the typed words and nothing of the trip, the project name or the household password")
def then_only_the_typed_words_were_sent(world: PlannerWorld) -> None:
    seen = only(place_server(world).requests("GET", "/search"), "requests the search service saw")
    assert seen.query["q"] == ["Gorges du Verdon"], seen.query
    assert set(seen.query) <= {"q", "format", "addressdetails", "limit"}, seen.query
    wire = json.dumps({"headers": seen.headers, "path": seen.path, "query": seen.query})
    assert "authorization" not in seen.headers and "cookie" not in seen.headers, seen.headers
    assert "Assietta" not in wire and world.scratch["password"] not in wire, wire


@then("the planner says the place search isn't answering")
def then_the_place_search_is_not_answering(world: PlannerWorld) -> None:
    response = state(world).response
    assert response is not None and response.status_code == 503, (
        f"the search answered {response and response.status_code}"
    )
    assert response.json()["code"] == "place_search_unavailable", response.json()


@then("the trip holds the same items as before")
def then_the_trip_is_unchanged(world: PlannerWorld) -> None:
    assert_state_delta(state(world).items_before, world.catalog_view(), CATALOG_UNIVERSE, {})
