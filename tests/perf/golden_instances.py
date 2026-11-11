"""The I1 (dense) and I2 (sparse) reference projects and their golden order (slice 03-ops; OD-7, D145, D146, D175).

    uv run python -m tests.perf.golden_instances write   # (re)write both instances under fixtures/golden/
    uv run python -m tests.perf.golden_instances bless   # plan both through the API and record their order

Method (spike findings.md, Setup): seed 20261101; 68 named Western Alps places (`western_alps_places.py`); Start
"Casa Marco, Torino", End "Briancon"; 40 tracks and 20 POIs drawn from the other places by the seed (62 stops). Every
track starts at its place and ends 2-40 km away at a seeded bearing; its recorded polyline is 1.4 x the straight line
(a seeded arc of `points_per_track` points, constant elevation). Road distances are the offline road map's (straight
line x 1.3). I2 adds a scripted road map (`i2-sparse.road-map.yaml`, MOCK_PLAN) that turns about 5 % of its required
pairs into one-way detours of 3 x the straight line (asymmetric costs); I1 uses the default road map. The spike's
own instances (order shas fb4c6f72..., 938136f7...) cannot be reproduced: its probe code and place table were
discarded at the promotion gate. This re-creates the method, not those instances.

The golden order (`expected_order`, `expected_order_sha256`) is written only by `bless`, never by hand: each instance
is planned through the HTTP API in a fresh in-process planner with the real OR-Tools child at the default budget
(10,000; I2 with its road map as MOCK_PLAN), Calculate with ignore_memo. A different committed order is overwritten
only with `bless --rebless`. `write` keeps the blessed order of an instance it regenerates unchanged.

D223: the golden is blessed on the current single GLS search (PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH stopped by the
solution count); two-phase weighting (ADR-016 section 4) is not built. Re-bless trigger: any change to the weighting
mode, the phase limits, the solver identity (SOLVER_IDENTITY), the default budget or the ortools version (for example
the 06a/06b two-phase weighting) re-blesses both instances, in a commit of its own.
Slice 03b does not re-bless: the model pin (`test_golden_model_pin.py`) and the golden test are the check, and a
failure of either is reported to the orchestrator, never fixed by `bless`.

`items` (70 for the D146 re-calibration) and `points_per_track` (20,000 for the D135 guard re-measure) give the 06-05
variants; they are written elsewhere (`--out`) on the fly and never committed. The fixture reader (`committed_trip`,
`TripData`) and `order_sha256` are defined here once, for the binding, the golden check and this generator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

from overland_planner.adapters.solver.ortools_tour_solver import SOLVER_IDENTITY
from tests.acceptance.overland_route_planner_mvp.steps.browser import REPO_ROOT
from tests.acceptance.overland_route_planner_mvp.steps.places import Place, distance_m
from tests.perf.western_alps_places import WESTERN_ALPS

if TYPE_CHECKING:  # performance_steps imports this module: the steps are imported where they run
    from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld

SEED = 20261101
I1_DENSE = "i1-dense"
I2_SPARSE = "i2-sparse"
KINDS = (I1_DENSE, I2_SPARSE)
COMMITTED = REPO_ROOT / "tests" / "acceptance" / "overland_route_planner_mvp" / "fixtures" / "golden"
START, END = "Casa Marco, Torino", "Briancon"
ITEMS = 60
POIS = 20
POINTS_PER_TRACK = 12
SOLVER_BUDGET = 10_000
EXIT_KM = (2.0, 40.0)
LENGTH_RATIO = 1.4
ELEVATION_M = 1500.0
DETOUR_FACTOR = 1.3  # the offline road map's default (MockRoutingProvider)
DETOUR_SHARE = 0.05
DETOUR_RATIO = 3.0
ROAD_SPEED_M_S = 60_000 / 3600
EXTRA_PLACE_KM = (3.0, 8.0)  # beyond the 66 drawable places (items > 66): a numbered place this far from another
EARTH_RADIUS_M = 6_371_000.0  # as `distance_m`
DECIMALS = 6  # the road map matches points at 6 decimals
BLESSING = ("expected_order", "expected_order_sha256", "solver_identity")
GOLDEN_NOTE = (
    "Blessed on the current single GLS search (D223). Re-bless both instances, in a commit of their own, on any "
    "change to the weighting mode, the phase limits, SOLVER_IDENTITY, the default budget or the ortools version "
    "(for example 06a/06b two-phase weighting)."
)
PLAN_DEADLINE_S = 600.0

Point = tuple[float, float]
TrackPoints = tuple[tuple[float, float, float], ...]


# ------------------------------------------------------------------------------------- the fixture reader
@dataclass(frozen=True)
class TripData:
    """A project as Marco would bring it: trail files, places, and the Start and End places."""

    tracks: tuple[tuple[str, tuple[tuple[float, float, float], ...]], ...]
    pois: tuple[tuple[str, float, float], ...]
    start: tuple[str, float, float]
    end: tuple[str, float, float]
    solver_budget: int | None = None
    expected_order: tuple[str, ...] = ()
    expected_order_sha256: str | None = None
    road_km: float | None = None

    @property
    def item_count(self) -> int:
        return len(self.tracks) + len(self.pois)


def committed_trip(path: Path) -> TripData:
    """The committed reference project (slice 03-ops). Format: see red-classification.md, slice 03 fixture contract."""
    assert path.exists(), (
        f"the committed reference project {path.relative_to(REPO_ROOT)} does not exist yet: slice 03-ops generates "
        "I1 (dense) and I2 (sparse) with seed 20261101 and commits them with their golden order"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    return TripData(
        tracks=tuple((t["name"], tuple(tuple(p) for p in t["points"])) for t in data["tracks"]),
        pois=tuple((p["name"], p["lat"], p["lon"]) for p in data["pois"]),
        start=(data["start"]["name"], data["start"]["lat"], data["start"]["lon"]),
        end=(data["end"]["name"], data["end"]["lat"], data["end"]["lon"]),
        solver_budget=data.get("solver_budget"),
        expected_order=tuple(data.get("expected_order", ())),
        expected_order_sha256=data.get("expected_order_sha256"),
    )


def order_sha256(names: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------- generation
@dataclass(frozen=True)
class Detour:
    origin: Point
    destination: Point
    distance_m: int
    duration_s: int


@dataclass(frozen=True)
class GoldenInstance:
    name: str
    seed: int
    items: int
    points_per_track: int
    trip: TripData
    road_map: tuple[Detour, ...] | None


def generate(
    kind: str, *, seed: int = SEED, items: int = ITEMS, points_per_track: int = POINTS_PER_TRACK
) -> GoldenInstance:
    if kind not in KINDS or items <= POIS or points_per_track < 3:
        raise ValueError(f"no instance {kind!r} of {items} items with {points_per_track} points per track")
    rng = random.Random(f"{seed}/{kind}")  # noqa: S311 - test data, not security
    places = _drawn_places(rng, items)
    tracks = tuple((place.name, _track(rng, place, points_per_track)) for place in places[: items - POIS])
    pois = tuple((place.name, *_point(place)) for place in places[items - POIS :])
    by_name = {place.name: place for place in WESTERN_ALPS}
    trip = TripData(tracks, pois, (START, *_point(by_name[START])), (END, *_point(by_name[END])), SOLVER_BUDGET)
    road_map = _detours(rng, trip) if kind == I2_SPARSE else None
    return GoldenInstance(kind, seed, items, points_per_track, trip, road_map)


def _point(place: Place) -> Point:
    return round(place.lat, DECIMALS), round(place.lon, DECIMALS)


def _drawn_places(rng: random.Random, items: int) -> list[Place]:
    others = [place for place in WESTERN_ALPS if place.name not in (START, END)]
    drawn = rng.sample(others, min(items, len(others)))
    for extra in range(items - len(others)):
        near = others[extra % len(others)]
        lat, lon = _destination(near.lat, near.lon, rng.uniform(0, 360), rng.uniform(*EXTRA_PLACE_KM) * 1000)
        drawn.append(Place(f"{near.name} {extra // len(others) + 2}", lat, lon))
    rng.shuffle(drawn)
    return drawn


def _track(rng: random.Random, entry: Place, points: int) -> TrackPoints:
    """An arc from the place to an exit 2-40 km away; its bulge makes the polyline 1.4 x the straight line."""
    straight_m = rng.uniform(*EXIT_KM) * 1000
    bearing = rng.uniform(0, 360)
    steps = [math.sin(math.pi * k / (points - 1)) for k in range(points)]
    bulge_m = _bulge_for_ratio(straight_m, steps)
    track = []
    for k, step in enumerate(steps):
        along = _destination(entry.lat, entry.lon, bearing, straight_m * k / (points - 1))
        lat, lon = _destination(*along, bearing + 90, bulge_m * step)
        track.append((round(lat, DECIMALS), round(lon, DECIMALS), ELEVATION_M))
    return tuple(track)


def _bulge_for_ratio(straight_m: float, steps: Sequence[float]) -> float:
    run_m = straight_m / (len(steps) - 1)
    rises = [b - a for a, b in pairwise(steps)]

    def ratio(bulge_m: float) -> float:
        return sum(math.hypot(run_m, bulge_m * rise) for rise in rises) / straight_m

    low, high = 0.0, straight_m
    for _ in range(60):
        middle = (low + high) / 2
        low, high = (middle, high) if ratio(middle) < LENGTH_RATIO else (low, middle)
    return (low + high) / 2


def _destination(lat: float, lon: float, bearing_deg: float, metres: float) -> Point:
    phi, lam, theta = math.radians(lat), math.radians(lon), math.radians(bearing_deg)
    delta = metres / EARTH_RADIUS_M
    phi2 = math.asin(math.sin(phi) * math.cos(delta) + math.cos(phi) * math.sin(delta) * math.cos(theta))
    lam2 = lam + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi), math.cos(delta) - math.sin(phi) * math.sin(phi2)
    )
    return math.degrees(phi2), math.degrees(lam2)


def _detours(rng: random.Random, trip: TripData) -> tuple[Detour, ...]:
    """About 5 % of the required pairs (from Start or an item's exit to an item's entry or End), one way only."""
    sources = [("start", trip.start[1:]), *((n, (lat, lon)) for n, lat, lon in trip.pois)]
    sources += [(name, track[-1][:2]) for name, track in trip.tracks]
    targets = [("end", trip.end[1:]), *((n, (lat, lon)) for n, lat, lon in trip.pois)]
    targets += [(name, track[0][:2]) for name, track in trip.tracks]
    required = [(a, b) for name_a, a in sources for name_b, b in targets if name_a != name_b and a != b]
    rng.shuffle(required)
    chosen: list[tuple[Point, Point]] = []
    taken: set[tuple[Point, Point]] = set()
    for origin, destination in required:
        if len(chosen) == round(DETOUR_SHARE * len(required)):
            break
        if (destination, origin) not in taken and (origin, destination) not in taken:
            chosen.append((origin, destination))
            taken.add((origin, destination))
    return tuple(_detour(origin, destination) for origin, destination in chosen)


def _detour(origin: Point, destination: Point) -> Detour:
    metres = max(1, round(DETOUR_RATIO * distance_m(*origin, *destination)))
    return Detour(origin, destination, metres, max(1, round(metres / ROAD_SPEED_M_S)))


# ------------------------------------------------------------------------------------------------ writing
def write(
    folder: Path,
    kind: str,
    *,
    seed: int = SEED,
    items: int = ITEMS,
    points_per_track: int = POINTS_PER_TRACK,
) -> tuple[Path, ...]:
    """Write one instance (I2: and its road map); an unchanged instance keeps its blessed order."""
    instance = generate(kind, seed=seed, items=items, points_per_track=points_per_track)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = folder / f"{kind}.json"
    document = _document(instance)
    document.update(_blessing_kept(fixture, document))
    written = [fixture]
    if instance.road_map is not None:
        road_map = folder / str(document["road_map"])
        road_map.write_text(_road_map_yaml(instance), encoding="utf-8")
        written.append(road_map)
    fixture.write_text(_dumps(document), encoding="utf-8")
    return tuple(written)


def _document(instance: GoldenInstance) -> dict[str, Any]:
    trip = instance.trip
    return {
        "name": instance.name,
        "seed": instance.seed,
        "generator": "tests/perf/golden_instances.py (uv run python -m tests.perf.golden_instances write, then bless)",
        "items": instance.items,
        "points_per_track": instance.points_per_track,
        "golden_note": GOLDEN_NOTE,
        "solver_budget": trip.solver_budget,
        "start": {"name": trip.start[0], "lat": trip.start[1], "lon": trip.start[2]},
        "end": {"name": trip.end[0], "lat": trip.end[1], "lon": trip.end[2]},
        "road_map": None if instance.road_map is None else f"{instance.name}.road-map.yaml",
        "tracks": [{"name": name, "points": [list(p) for p in points]} for name, points in trip.tracks],
        "pois": [{"name": name, "lat": lat, "lon": lon} for name, lat, lon in trip.pois],
        "expected_order": [],
        "expected_order_sha256": None,
        "solver_identity": None,
    }


def _blessing_kept(fixture: Path, document: dict[str, Any]) -> dict[str, Any]:
    if not fixture.exists():
        return {}
    committed = json.loads(fixture.read_text(encoding="utf-8"))
    if {k: v for k, v in committed.items() if k not in BLESSING} != _instance_part(document):
        return {}
    return {key: committed.get(key) for key in BLESSING}


def _instance_part(document: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps({k: v for k, v in document.items() if k not in BLESSING}))


def _dumps(document: dict[str, Any]) -> str:
    """JSON with one track, POI or stop per line: small diffs on a re-bless, readable by hand."""
    lines = []
    for key, value in document.items():
        head = f"  {json.dumps(key)}: "
        if isinstance(value, list) and value:
            rows = ",\n".join(f"    {json.dumps(row, ensure_ascii=False)}" for row in value)
            lines.append(f"{head}[\n{rows}\n  ]")
        else:
            lines.append(head + json.dumps(value, ensure_ascii=False))
    return "{\n" + ",\n".join(lines) + "\n}\n"


def _road_map_yaml(instance: GoldenInstance) -> str:
    assert instance.road_map is not None
    rows = "".join(
        f"  - {{from: [{d.origin[0]!r}, {d.origin[1]!r}], to: [{d.destination[0]!r}, {d.destination[1]!r}], "
        f"distance_m: {d.distance_m}, duration_s: {d.duration_s}}}\n"
        for d in instance.road_map
    )
    return (
        f"# Scripted road map (MOCK_PLAN) of {instance.name}, written by tests/perf/golden_instances.py "
        f"(seed {instance.seed}); never edit by hand.\n"
        f"# {len(instance.road_map)} one-way detours of {DETOUR_RATIO:g} x the straight line, about "
        f"{DETOUR_SHARE:.0%} of the instance's required pairs, at {ROAD_SPEED_M_S * 3.6:g} km/h.\n"
        f"# Every other pair keeps the default: straight line x {DETOUR_FACTOR}.\n"
        f"detour_factor: {DETOUR_FACTOR}\n"
        f"pairs:\n{rows}"
    )


# ------------------------------------------------------------------------------------------------ blessing
class GoldenOrderConflictError(RuntimeError):
    """The planner returns an order other than the committed golden one; only an explicit re-bless replaces it."""


Plan = Callable[[TripData, Path | None], Sequence[str]]


def bless(folder: Path, kind: str, *, plan: Plan | None = None, rebless: bool = False) -> list[str]:
    """Plan the written instance and record its stop names and their sha256 in the fixture."""
    fixture = folder / f"{kind}.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    trip = committed_trip(fixture)
    road_map = folder / document["road_map"] if document["road_map"] else None
    order = list((plan or plan_through_api)(trip, road_map))
    stops = [trip.start[0], *(name for name, _ in trip.tracks), *(name for name, *_ in trip.pois), trip.end[0]]
    if sorted(order) != sorted(stops) or (order[0], order[-1]) != (trip.start[0], trip.end[0]):
        raise ValueError(f"{kind}: the plan does not visit every stop once from Start to End: {order}")
    committed = document["expected_order"]
    if committed and committed != order and not rebless:
        raise GoldenOrderConflictError(
            f"{kind}: the planner now returns {order_sha256(order)}, the committed golden order is "
            f"{document['expected_order_sha256']}; re-bless explicitly (bless --rebless) in a commit of its own"
        )
    document.update(expected_order=order, expected_order_sha256=order_sha256(order), solver_identity=SOLVER_IDENTITY)
    fixture.write_text(_dumps(document), encoding="utf-8")
    return order


@dataclass(frozen=True)
class PlannedOrder:
    """The stop names of a finished plan, the last poll of its job (`elapsed_s`; `stage_ms` from 06-03) and the wall
    seconds from Calculate to the end seen by the poll (an in-process planner runs on a fake clock)."""

    names: tuple[str, ...]
    job: dict[str, Any]
    wall_s: float


def plan_through_api(trip: TripData, road_map: Path | None) -> list[str]:
    return list(plan_in_fresh_planner(trip, road_map).names)


def plan_in_fresh_planner(trip: TripData, road_map: Path | None) -> PlannedOrder:
    """A fresh in-process planner, the real OR-Tools child, the default budget; Calculate with ignore_memo."""
    from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld
    from tests.common.fakes import FakeClock, FakeMountTable
    from tests.common.workspace import workspace_data_dir

    with workspace_data_dir("golden") as data_dir:
        environ = {"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock", "LOG_LEVEL": "INFO"}
        if road_map is not None:
            environ["MOCK_PLAN"] = str(road_map)
        world = PlannerWorld(data_dir.parent, data_dir, environ, FakeClock(), FakeMountTable())
        try:
            return plan_on(world, "golden", trip)
        finally:
            world.shutdown()


def plan_on(world: PlannerWorld, project: str, trip: TripData) -> PlannedOrder:
    """Bring the trip as a new project to the world's planner and plan it once (the bless and the golden check)."""
    from tests.acceptance.overland_route_planner_mvp.steps import performance_steps as steps

    steps.bring_trip(world, project, trip)
    steps.press(world, ignore_memo=True)
    job = steps.finish(world, PLAN_DEADLINE_S)
    assert job["state"] == "done", f"the plan did not finish: {job}"
    detail = steps.latest_run(world)
    steps.assert_ready(detail)
    wall_s = float(world.scratch["ended_at"] - world.scratch["pressed_at"])
    return PlannedOrder(tuple(steps.stop_names(detail)), job, wall_s)


# ---------------------------------------------------------------------------------------------------- CLI
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.perf.golden_instances", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("write", "bless"))
    parser.add_argument("--kind", choices=KINDS, action="append", help="default: both")
    parser.add_argument("--out", type=Path, default=COMMITTED)
    parser.add_argument("--items", type=int, default=ITEMS)
    parser.add_argument("--points-per-track", type=int, default=POINTS_PER_TRACK)
    parser.add_argument("--rebless", action="store_true", help="replace a different committed golden order")
    arguments = parser.parse_args(argv)
    variant = (arguments.items, arguments.points_per_track) != (ITEMS, POINTS_PER_TRACK)
    if variant and arguments.out.resolve() == COMMITTED.resolve():
        parser.error("variants are generated on the fly and never committed: give --out")
    for kind in arguments.kind or KINDS:
        if arguments.command == "write":
            paths = write(arguments.out, kind, items=arguments.items, points_per_track=arguments.points_per_track)
            print(f"{kind}: wrote {', '.join(p.name for p in paths)}")
            continue
        order = bless(arguments.out, kind, rebless=arguments.rebless)
        print(f"{kind}: blessed {len(order)} stops, sha256 {order_sha256(order)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
