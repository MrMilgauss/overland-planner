"""The fingerprint of the solver inputs (ADR-014 section 5, D124, FR-5.6): the memo key of a plan's order. Pure domain.

Driving port: `Fingerprint.of`, the function the plan job calls. Observable universe: the fingerprint value.
Test Budget: 2 behaviors (rebuilding the same inputs, or changing what only the totals use, keeps the fingerprint;
changing any single input gives another) x 2 = 4; 2 used. Every single-input change is applied on every generated
model (D212), not one random draw.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem
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


def _moved(point: Coordinate) -> Coordinate:
    return Coordinate(point.latitude + 0.001, point.longitude)


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

    return {
        "item": (with_added, _model_with_legs(trip, with_added), solve),
        "anchor": (with_new_start, _model_with_legs(trip, with_new_start), solve),
        "track direction version": (track_as(direction_version=track.direction_version + 1), model, solve),
        "track entry": (track_as(entry=_moved(track.entry)), model, solve),
        "track exit": (track_as(exit=_moved(track.exit)), model, solve),
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
