"""Trip anchors (HC-2, D6, brief §5 D183): exactly one Start and one End, POIs of the project only.

Driving port: the pure domain value `Anchors` (`Anchors.chosen(...)` and `marked(items)` are its public interface).
Observable universe = the item rows as listed (`project.items`: id, type, anchor) and the refusal, if any.
Test Budget: 2 behaviors (chosen rows carry the anchors, non-POI or foreign choice refused) x 2 = 4; 2 used.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.anchors import AnchorNotAPlaceError, Anchors
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.catalog.poi import PoiItem
from tests.common.predicates import rows_replaced
from tests.common.state_delta import assert_state_delta, set_to

PROJECT = "p"
UNIVERSE = {"project.items", "refusal"}
HERE = Coordinate(45.07, 7.69)


def _poi(index: int, project_id: str = PROJECT) -> PoiItem:
    return PoiItem(id=f"{project_id}-poi-{index}", project_id=project_id, name=f"Place {index}", location=HERE)


def _track(index: int) -> TrackItem:
    return TrackItem(
        id=f"{PROJECT}-track-{index}",
        project_id=PROJECT,
        name=f"Trail {index}",
        description=None,
        original_sha256="a",
        canonical_sha256="b",
        direction_version=1,
        point_count=2,
        entry=HERE,
        exit=HERE,
        length_m=1.0,
    )


@st.composite
def catalogs(draw: st.DrawFn) -> list[CatalogItem]:
    """A project's items: 1-8 POIs and 0-4 tracks in any order."""
    pois = [_poi(i) for i in range(draw(st.integers(1, 8)))]
    tracks = [_track(i) for i in range(draw(st.integers(0, 4)))]
    return draw(st.permutations([*pois, *tracks]))


def _view(items: list[CatalogItem], refusal: str | None = None) -> dict[str, Any]:
    return {"project.items": tuple((item.id, item.type, item.anchor) for item in items), "refusal": refusal}


def _place_ids(items: list[CatalogItem]) -> list[str]:
    return [item.id for item in items if isinstance(item, PoiItem)]


@given(data=st.data(), items=catalogs())
def test_exactly_the_chosen_places_carry_start_and_end_and_the_same_place_shows_one_start_end_row(
    data: st.DataObject, items: list[CatalogItem]
) -> None:
    by_id = {item.id: item for item in items}
    places = _place_ids(items)
    old_start, old_end, start, end = (data.draw(st.sampled_from(places)) for _ in range(4))
    before = _view(Anchors.chosen(PROJECT, by_id[old_start], by_id[old_end]).marked(items))

    after = _view(Anchors.chosen(PROJECT, by_id[start], by_id[end]).marked(items))

    anchors = {start: "start_end"} if start == end else {start: "start", end: "end"}
    replaced = {row[0]: (row[0], row[1], anchors.get(row[0])) for row in before["project.items"]}
    expected = {"project.items": rows_replaced(replaced, key_index=0)}
    assert_state_delta(before, after, UNIVERSE, expected, strict=True)
    assert sum(row[2] is not None for row in after["project.items"]) == len(anchors)


@given(data=st.data(), items=catalogs().filter(lambda items: any(isinstance(i, TrackItem) for i in items)))
def test_a_track_or_a_place_of_another_project_is_refused_as_start_or_end(
    data: st.DataObject, items: list[CatalogItem]
) -> None:
    places = [item for item in items if isinstance(item, PoiItem)]
    refused = data.draw(st.sampled_from([item for item in items if isinstance(item, TrackItem)] + [_poi(0, "q")]))
    place = data.draw(st.sampled_from(places))
    start, end = data.draw(st.sampled_from([(refused, place), (place, refused), (refused, refused)]))
    before = _view(items)

    with pytest.raises(AnchorNotAPlaceError) as refusal:
        Anchors.chosen(PROJECT, start, end)

    after = _view(items, str(refusal.value))
    expected = {"refusal": set_to("Only a place of this project can be the Start or End")}
    assert_state_delta(before, after, UNIVERSE, expected, strict=True)
