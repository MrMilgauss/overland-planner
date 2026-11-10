"""The I1/I2 generator, its golden check and its fixture reader (slice 03-ops, OD-7, D145, D146, D175, D223).

Universe: the fixture files of a golden folder (`i1-dense.json`, `i2-sparse.json`, `i2-sparse.road-map.yaml`), each
read as its bytes (None while absent). Writing or blessing one instance changes only that instance's files.
The bless tests plan through a stand-in `plan` (the real one is the HTTP API with the OR-Tools child, ~20 s per
instance); the committed golden itself is checked by "The 60-item plan is the same on every machine".
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.bootstrap.app_factory import ExternalPorts
from tests.acceptance.overland_route_planner_mvp.steps.places import distance_m
from tests.acceptance.overland_route_planner_mvp.steps.planner import InProcessPlanner
from tests.common.fakes import FakeClock, FakeMountTable
from tests.common.state_delta import assert_state_delta, set_to, unchanged
from tests.common.workspace import workspace_data_dir
from tests.perf.golden_instances import (
    COMMITTED,
    I1_DENSE,
    I2_SPARSE,
    SEED,
    GoldenOrderConflictError,
    TripData,
    bless,
    committed_trip,
    generate,
    order_sha256,
    write,
)
from tests.perf.western_alps_places import WESTERN_ALPS

FILES = ("i1-dense.json", "i2-sparse.json", "i2-sparse.road-map.yaml")
UNIVERSE = set(FILES)
FILES_OF = {I1_DENSE: {"i1-dense.json"}, I2_SPARSE: {"i2-sparse.json", "i2-sparse.road-map.yaml"}}
START, END = "Casa Marco, Torino", "Briancon"
PLACE_AT = {(p.lat, p.lon): p.name for p in WESTERN_ALPS}

kinds = st.sampled_from((I1_DENSE, I2_SPARSE))
seeds = st.integers(min_value=0, max_value=2**32 - 1)
item_counts = st.integers(min_value=21, max_value=80)  # 20 POIs and at least one track; 70 for D146
# 6-decimal points resolve ~0.1 m: the 1 % length ratio holds while segments are metres long. The 20,000-point
# variant of 06-05 (D135 guard) is about import size, not the ratio, and is not drawn here.
points_per_track = st.integers(min_value=3, max_value=40)
FILE_EXAMPLES = 100  # tests that write files: capped below the ci profile's 1,000 (54 s -> 15 s); still seeded


@contextmanager
def golden_folder() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as folder:
        yield Path(folder)


def fixture_files(folder: Path) -> dict[str, bytes | None]:
    return {name: (folder / name).read_bytes() if (folder / name).exists() else None for name in FILES}


def polyline_m(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(distance_m(a[0], a[1], b[0], b[1]) for a, b in pairwise(points))


def all_stops(trip: TripData) -> list[str]:
    return [trip.start[0], *(name for name, _ in trip.tracks), *(name for name, *_ in trip.pois), trip.end[0]]


def planned_by(order: Callable[[list[str]], list[str]]) -> Callable[[TripData, Path | None], list[str]]:
    """A stand-in for the API plan: Start, `order` of the items, End."""

    def plan(trip: TripData, road_map: Path | None) -> list[str]:
        return [trip.start[0], *order(all_stops(trip)[1:-1]), trip.end[0]]

    return plan


def only_keys_changed(*keys: str) -> Callable[[Any, Any], bool]:
    """The fixture file changed only in `keys` (state delta inside one file slot)."""

    def predicate(old: bytes | None, new: bytes | None) -> bool:
        before, after = json.loads(old or b"{}"), json.loads(new or b"{}")
        return {k: v for k, v in before.items() if k not in keys} == {k: v for k, v in after.items() if k not in keys}

    predicate.__name__ = f"only_keys_changed({keys})"
    return predicate


# ------------------------------------------------------------------------------------------------- write
@given(kind=kinds, seed=seeds, items=item_counts, points=points_per_track)
@settings(deadline=None, max_examples=FILE_EXAMPLES)
def test_writing_an_instance_is_byte_identical_and_touches_only_its_own_files(
    kind: str, seed: int, items: int, points: int
) -> None:
    with golden_folder() as folder:
        other = I2_SPARSE if kind == I1_DENSE else I1_DENSE
        write(folder, other, seed=seed, items=items, points_per_track=points)
        before = fixture_files(folder)
        write(folder, kind, seed=seed, items=items, points_per_track=points)
        first = fixture_files(folder)
        write(folder, kind, seed=seed, items=items, points_per_track=points)
        after = fixture_files(folder)
    assert all(first[name] is not None for name in FILES_OF[kind]), f"{kind} wrote {first}"
    expected = {name: set_to(first[name]) for name in FILES_OF[kind]}
    assert_state_delta(before, after, UNIVERSE, {**expected, **{n: unchanged() for n in FILES_OF[other]}}, strict=True)


# --------------------------------------------------------------------------------------------- the shape
@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(kind=kinds, seed=seeds, items=item_counts, points=points_per_track)
@settings(deadline=None)
def test_every_instance_keeps_its_shape(kind: str, seed: int, items: int, points: int) -> None:
    instance = generate(kind, seed=seed, items=items, points_per_track=points)
    trip = instance.trip
    assert generate(kind, seed=seed, items=items, points_per_track=points) == instance, "not deterministic"
    names = all_stops(trip)
    assert (len(trip.tracks), len(trip.pois), trip.start[0], trip.end[0]) == (items - 20, 20, START, END)
    assert len(set(names)) == len(names) == items + 2, f"names are not unique: {names}"
    assert PLACE_AT.get(trip.start[1:]) == START and PLACE_AT.get(trip.end[1:]) == END
    if items <= len(WESTERN_ALPS) - 2:
        assert all(PLACE_AT.get((lat, lon)) == name for name, lat, lon in trip.pois), "a POI is not at its place"
    for name, track in trip.tracks:
        assert len(track) == points, f"{name} has {len(track)} points"
        entry, exit_ = track[0], track[-1]
        if items <= len(WESTERN_ALPS) - 2:
            assert PLACE_AT.get(entry[:2]) == name, f"{name} does not start at its place"
        straight = distance_m(entry[0], entry[1], exit_[0], exit_[1])
        assert 2_000 - 1 <= straight <= 40_000 + 1, f"{name} ends {straight:.0f} m from its entry"
        assert math.isclose(polyline_m(track), 1.4 * straight, rel_tol=0.01), f"{name}: {polyline_m(track):.0f} m"


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(seed=seeds, items=item_counts)
@settings(deadline=None, max_examples=FILE_EXAMPLES)
def test_the_sparse_road_map_turns_about_five_percent_of_its_own_pairs_into_one_way_detours(
    seed: int, items: int
) -> None:
    trip = generate(I2_SPARSE, seed=seed, items=items, points_per_track=3).trip
    assert generate(I1_DENSE, seed=seed, items=items, points_per_track=3).road_map is None, "I1 has a road map"
    sources = {trip.start[1:], *((p[1], p[2]) for p in trip.pois), *(t[-1][:2] for _, t in trip.tracks)}
    targets = {trip.end[1:], *((p[1], p[2]) for p in trip.pois), *(t[0][:2] for _, t in trip.tracks)}
    required = len(sources) * len(targets) - len(trip.pois) - len(trip.tracks)  # an item never leads to itself
    with golden_folder() as folder:
        write(folder, I2_SPARSE, seed=seed, items=items, points_per_track=3)
        road_map = yaml.safe_load((folder / "i2-sparse.road-map.yaml").read_text(encoding="utf-8"))
        assert json.loads((folder / "i2-sparse.json").read_text(encoding="utf-8"))["road_map"] == FILES[2]
    pairs = [(tuple(p["from"]), tuple(p["to"]), p["distance_m"], p["duration_s"]) for p in road_map["pairs"]]
    assert road_map["detour_factor"] == 1.3
    assert 0.04 * required <= len(pairs) <= 0.05 * required + 1, f"{len(pairs)} detours of {required} pairs"
    listed = {(origin, destination) for origin, destination, *_ in pairs}
    for origin, destination, metres, seconds in pairs:
        assert origin in sources and destination in targets, f"{origin} -> {destination} is not one of I2's pairs"
        assert (destination, origin) not in listed, f"{origin} <-> {destination} is a detour both ways"
        assert abs(metres - 3 * distance_m(*origin, *destination)) <= 1, f"{origin} -> {destination}: {metres} m"
        assert seconds == max(1, round(metres / (60_000 / 3600))), f"{metres} m in {seconds} s is not 60 km/h"


# ------------------------------------------------------------------------------- the order and its hash
@given(names=st.lists(st.text(min_size=1), min_size=2, max_size=70, unique=True), data=st.data())
def test_two_different_orders_of_the_same_names_have_different_hashes(names: list[str], data: st.DataObject) -> None:
    other = data.draw(st.permutations(names).filter(lambda p: list(p) != names))
    assert order_sha256(names) != order_sha256(other)


@given(kind=kinds, seed=seeds, shuffle=st.randoms(use_true_random=False))
@settings(deadline=None, max_examples=FILE_EXAMPLES)
def test_blessing_writes_the_planned_order_and_the_reader_gives_it_back(kind: str, seed: int, shuffle: Any) -> None:
    with golden_folder() as folder:
        write(folder, kind, seed=seed)
        before = fixture_files(folder)
        order = bless(folder, kind, plan=planned_by(lambda items: shuffle.sample(items, len(items))))
        after = fixture_files(folder)
        trip = committed_trip(folder / f"{kind}.json")
    file_name = f"{kind}.json"
    assert_state_delta(
        before,
        after,
        UNIVERSE,
        {file_name: only_keys_changed("expected_order", "expected_order_sha256", "solver_identity")},
        strict=True,
    )
    assert list(trip.expected_order) == order and trip.expected_order_sha256 == order_sha256(order)
    assert sorted(order) == sorted(all_stops(trip)) and (order[0], order[-1]) == (START, END)


@given(kind=kinds, rebless=st.booleans())
@settings(deadline=None, max_examples=10)
def test_a_different_committed_order_is_overwritten_only_on_an_explicit_rebless(kind: str, rebless: bool) -> None:
    with golden_folder() as folder:
        write(folder, kind, seed=SEED)
        bless(folder, kind, plan=planned_by(sorted))
        before = fixture_files(folder)
        if rebless:
            bless(folder, kind, plan=planned_by(lambda items: sorted(items, reverse=True)), rebless=True)
        else:
            with pytest.raises(GoldenOrderConflictError):
                bless(folder, kind, plan=planned_by(lambda items: sorted(items, reverse=True)))
        write(folder, kind, seed=SEED)  # regenerating the same instance keeps whatever order is blessed
        after = fixture_files(folder)
    file_name = f"{kind}.json"
    changed = only_keys_changed("expected_order", "expected_order_sha256") if rebless else unchanged()
    assert_state_delta(before, after, UNIVERSE, {file_name: changed}, strict=True)
    assert (before[file_name] != after[file_name]) is rebless


# ----------------------------------------------------------------------------------- integration (wiring)
def test_the_planner_starts_with_the_committed_sparse_road_map() -> None:
    """Single example (wiring): the committed I2 road map is a MOCK_PLAN the planner accepts at start-up."""
    with workspace_data_dir("perf") as data_dir:
        environ = {"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock", "MOCK_PLAN": str(COMMITTED / FILES[2])}
        planner = InProcessPlanner(environ, ExternalPorts(clock=FakeClock(), mount_table=FakeMountTable()))
        planner.start()
        try:
            health: httpx.Response = planner.session().health()
        finally:
            planner.stop()
    assert health.status_code == 200, f"{health.status_code} {health.text[:300]}"


def test_the_committed_instances_are_what_the_generator_writes() -> None:
    """Single example (golden check): regenerating with seed 20261101 leaves the committed files byte-identical."""
    with golden_folder() as folder:
        for name in FILES:
            (folder / name).write_bytes((COMMITTED / name).read_bytes())
        before = fixture_files(folder)
        write(folder, I1_DENSE)
        write(folder, I2_SPARSE)
        after = fixture_files(folder)
    assert_state_delta(before, after, UNIVERSE, {}, strict=True)
    for kind in (I1_DENSE, I2_SPARSE):
        trip = committed_trip(COMMITTED / f"{kind}.json")
        assert len(trip.expected_order) == 62 and trip.expected_order_sha256 == order_sha256(trip.expected_order)
