"""The fingerprint of the solver inputs (ADR-014 section 5, D124, FR-5.6): the memo key of a plan's order. Pure domain.

Driving port: `Fingerprint.of`, the function the plan job calls. Observable universe: the fingerprint value.
Test Budget: 3 behaviors (rebuilding the same inputs, or changing what only the totals use, or moving a point by less
than the quantum, keeps the fingerprint; changing any single input gives another; stored fingerprints never change
silently) x 2 = 6; 3 used. Every single-input change is applied on every generated model (D212), not one random draw.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from overland_planner.domain.catalog.project import OffroadSpeed
from overland_planner.domain.planning.fingerprint import FINGERPRINT_SCHEME, Fingerprint, SolveSettings
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import SolverModelBuilder, TourModel
from tests.common.state_delta import assert_state_delta, unchanged
from tests.unit.domain.planning.trips import PROJECT, Trip, trips

UNIVERSE = {"fingerprint"}
SETTINGS = SolveSettings(
    objective="distance",
    provider_id="mock:straight_line_x1.3",
    budget=500,
    solver_identity="ortools==9.15.6755;PATH_CHEAPEST_ARC;GUIDED_LOCAL_SEARCH",
)
Inputs = tuple[ProjectSnapshot, TourModel, SolveSettings]


def _changed(old: Any, new: Any) -> bool:
    return bool(old != new)


def _fingerprint(inputs: Inputs) -> dict[str, str]:
    snapshot, model, solve = inputs
    return {"fingerprint": Fingerprint.of(snapshot, model, solve).value}


def _inputs_of(trip: Trip) -> Inputs:
    return trip.snapshot, SolverModelBuilder(trip.snapshot).build(trip.legs), SETTINGS


def _with_item(
    snapshot: ProjectSnapshot, item_id: str, change: Callable[[CatalogItem], CatalogItem]
) -> ProjectSnapshot:
    return replace(snapshot, items=tuple(change(item) if item.id == item_id else item for item in snapshot.items))


ABOVE_QUANTUM = 0.001  # about 100 m: more than the 6-decimal quantum, less than a degree
BELOW_QUANTUM = 4e-7  # under half the 6-decimal quantum: the same quantised point


def _moved(point: Coordinate, latitude: float = 0.0, longitude: float = 0.0) -> Coordinate:
    return Coordinate(point.latitude + latitude, point.longitude + longitude)


def _nudged(item: CatalogItem, by: float) -> CatalogItem:
    """The item with every point moved by `by` degrees, north and east."""
    if isinstance(item, TrackItem):
        return replace(item, entry=_moved(item.entry, by, by), exit=_moved(item.exit, by, by))
    return replace(item, location=_moved(item.location, by, by))


def _one_more_arc_metre(model: TourModel) -> TourModel:
    """The first arc that exists costs one metre more: one leg distance changed and nothing else."""
    rows = [list(row) for row in model.arc_m]
    origin, destination = next((a, b) for a, row in enumerate(rows) for b, cost in enumerate(row) if cost is not None)
    rows[origin][destination] = (rows[origin][destination] or 0) + 1
    return replace(model, arc_m=tuple(tuple(row) for row in rows))


def _single_input_changes(trip: Trip) -> dict[str, Inputs]:
    """Every fingerprint input changed alone, on this trip (the trip has an Included track)."""
    snapshot, model, solve = _inputs_of(trip)
    track = trip.tracks()[0]
    new_start = PoiItem(id="another-start", project_id=PROJECT, name="Altrove", location=trip.start.location)
    with_new_start = replace(snapshot, start_item_id=new_start.id, items=(*snapshot.items, new_start))
    added = PoiItem(id="one-more-place", project_id=PROJECT, name="Rifugio", location=trip.start.location)
    with_added = replace(snapshot, items=(*snapshot.items, added))

    def track_as(**fields: Any) -> ProjectSnapshot:
        return _with_item(snapshot, track.id, lambda item: replace(item, **fields))

    def place_at(location: Coordinate) -> ProjectSnapshot:
        return _with_item(snapshot, trip.start.id, lambda item: replace(item, location=location))

    return {
        "item": (with_added, _model_with_legs(trip, with_added), solve),
        "anchor": (with_new_start, _model_with_legs(trip, with_new_start), solve),
        "track direction version": (track_as(direction_version=track.direction_version + 1), model, solve),
        "track entry latitude": (track_as(entry=_moved(track.entry, latitude=ABOVE_QUANTUM)), model, solve),
        "track entry longitude": (track_as(entry=_moved(track.entry, longitude=ABOVE_QUANTUM)), model, solve),
        "track exit latitude": (track_as(exit=_moved(track.exit, latitude=ABOVE_QUANTUM)), model, solve),
        "track exit longitude": (track_as(exit=_moved(track.exit, longitude=ABOVE_QUANTUM)), model, solve),
        "place latitude": (place_at(_moved(trip.start.location, latitude=ABOVE_QUANTUM)), model, solve),
        "place longitude": (place_at(_moved(trip.start.location, longitude=ABOVE_QUANTUM)), model, solve),
        "track points": (track_as(canonical_sha256="0" * 64), model, solve),
        "leg distance": (snapshot, _one_more_arc_metre(model), solve),
        "road map": (snapshot, model, replace(solve, provider_id="mock:straight_line_x1.3:script:" + "1" * 64)),
        "objective": (snapshot, model, replace(solve, objective="time")),
        "budget": (snapshot, model, replace(solve, budget=solve.budget + 1)),
        "solver identity": (snapshot, model, replace(solve, solver_identity="ortools==9.16;PATH_CHEAPEST_ARC")),
    }


def _model_with_legs(trip: Trip, snapshot: ProjectSnapshot) -> TourModel:
    """The model of a changed snapshot over the trip's road legs (its points come from the same pool)."""
    return SolverModelBuilder(snapshot).build(trip.legs)


def _with_a_track(trip: Trip) -> bool:
    return bool(trip.tracks())


@settings(deadline=None)
@given(
    trip=trips(),
    speed=st.floats(0.5, 120.0).map(OffroadSpeed),
    name=st.sampled_from(("Col de l'Izoard", "Passo")),
)
def test_rebuilding_the_same_inputs_or_changing_only_what_totals_use_keeps_the_fingerprint(
    trip: Trip, speed: OffroadSpeed, name: str
) -> None:
    before = _fingerprint(_inputs_of(trip))
    copied = ProjectSnapshot(trip.snapshot.start_item_id, trip.snapshot.end_item_id, tuple(trip.snapshot.items))
    renamed = replace(copied, items=tuple(replace(item, name=name) for item in copied.items), offroad_speed=speed)
    excluded = PoiItem(id="excluded-later", project_id=PROJECT, name=name, location=trip.start.location, included=False)
    rebuilt = replace(renamed, items=(*renamed.items, excluded))

    after = _fingerprint((rebuilt, SolverModelBuilder(rebuilt).build(trip.legs), replace(SETTINGS)))

    assert_state_delta(before, after, UNIVERSE, {"fingerprint": unchanged()}, strict=True)
    assert after["fingerprint"].startswith(f"{FINGERPRINT_SCHEME}:"), "the scheme version leads the fingerprint"
    snapshot, model, solve = _inputs_of(trip)
    nudged = replace(snapshot, items=tuple(_nudged(item, BELOW_QUANTUM) for item in snapshot.items))
    assert _fingerprint((nudged, model, solve)) == before, "a move below the quantum is the same point"


@settings(deadline=None)
@given(trip=trips().filter(_with_a_track))
def test_changing_any_single_solver_input_gives_another_fingerprint(trip: Trip) -> None:
    before = _fingerprint(_inputs_of(trip))

    for name, changed in _single_input_changes(trip).items():
        after = _fingerprint(changed)

        try:
            assert_state_delta(before, after, UNIVERSE, {"fingerprint": _changed}, strict=True)
        except AssertionError as error:
            raise AssertionError(f"changing the {name} kept the fingerprint: {error}") from error


GOLDEN_START = PoiItem(id="home", project_id=PROJECT, name="Casa Marco", location=Coordinate(45.0703391, 7.6868572))
GOLDEN_TRACK = TrackItem(
    id="assietta",
    project_id=PROJECT,
    name="Strada dell'Assietta",
    description=None,
    original_sha256="original",
    canonical_sha256="ab" * 32,
    direction_version=2,
    point_count=23_295,
    entry=Coordinate(45.0512345678, 7.0412345678),
    exit=Coordinate(44.9687654321, 6.8787654321),
    length_m=224_800.0,
)
GOLDEN_END = PoiItem(id="briancon", project_id=PROJECT, name="Briancon", location=Coordinate(44.8986, 6.6436))
GOLDEN_SNAPSHOT = ProjectSnapshot(GOLDEN_START.id, GOLDEN_END.id, (GOLDEN_START, GOLDEN_TRACK, GOLDEN_END))
GOLDEN_MODEL = TourModel(
    ("home", "assietta", "briancon"), 0, 2, ((None, 61_200, 140_100), (None, None, 27_400), (None, None, None))
)
# sha256 of the canonical JSON written out by hand (sorted keys, no spaces, points to 6 decimals), not by `of`.
GOLDEN_FINGERPRINT = "fp1:25884a670e4a16fba2b8861de399124b0188982c895b62316a1dbe64936167e3"


def test_the_fingerprint_of_fixed_inputs_is_pinned_so_stored_fingerprints_never_change_silently() -> None:
    """Runs keep their fingerprint in the database: a change of this value must bump FINGERPRINT_SCHEME (ADR-014
    section 5), so old memo entries miss instead of matching inputs they were not computed from."""
    assert Fingerprint.of(GOLDEN_SNAPSHOT, GOLDEN_MODEL, SETTINGS).value == GOLDEN_FINGERPRINT
