"""AnchorService (US-02c, HC-2, brief §5): Marco sets the Start and End of a trip among the project's POIs.

Driving ports: `AnchorService` with `PoiService` and `ProjectService` from the catalog facade. Driven port:
`CatalogUnitOfWork` (in-memory double honouring commit). Observable universe = what Marco sees through the driving
ports: `project.items` (name, type, anchor) and `project.revision` of the open project.
Test Budget: 3 behaviors (anchors replace the previous ones + revision, a refused anchor changes nothing, an unknown
project or item is not found, any choice of POIs, tracks, foreign items and unset anchors) x 2 = 8; 4 used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import (
    AnchorService,
    ItemNotFoundError,
    PoiService,
    ProjectNotFoundError,
    ProjectService,
)
from overland_planner.domain.catalog.anchors import AnchorNotAPlaceError
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import TrackItem
from tests.common.catalog_fakes import InMemoryCatalog
from tests.common.fakes import FakeClock
from tests.common.predicates import rows_replaced
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"project.items", "project.revision"}
PLACE_COUNT = st.integers(min_value=1, max_value=6)


def _catalog(place_count: int) -> tuple[AnchorService, ProjectService, PoiService, str, list[str]]:
    catalog = InMemoryCatalog()
    projects = ProjectService(catalog.unit_of_work, FakeClock(datetime(2027, 6, 1, tzinfo=UTC)))
    pois = PoiService(catalog.unit_of_work)
    project_id = projects.create("Alpi Occidentali giugno 2027").id
    ids = [pois.add(project_id, f"Place {i}", 45.0, 7.0).id for i in range(place_count)]
    return AnchorService(catalog.unit_of_work), projects, pois, project_id, ids


def _view(projects: ProjectService, project_id: str) -> dict[str, Any]:
    return {
        "project.items": tuple((item.name, item.type, item.anchor) for item in projects.items(project_id)),
        "project.revision": projects.open(project_id).revision,
    }


@given(data=st.data(), place_count=PLACE_COUNT)
def test_new_anchors_replace_the_previous_ones_and_add_one_revision(data: st.DataObject, place_count: int) -> None:
    anchors, projects, _, project_id, ids = _catalog(place_count)
    anchors.set(project_id, data.draw(st.sampled_from(ids)), data.draw(st.sampled_from(ids)))
    start, end = data.draw(st.sampled_from(ids)), data.draw(st.sampled_from(ids))
    before = _view(projects, project_id)

    anchors.set(project_id, start, end)

    names = {item.id: item.name for item in projects.items(project_id)}
    roles = {names[start]: "start_end"} if start == end else {names[start]: "start", names[end]: "end"}
    replaced = {name: (name, "poi", roles.get(name)) for name in names.values()}
    expected = {
        "project.items": rows_replaced(replaced, key_index=0),
        "project.revision": set_to(before["project.revision"] + 1),
    }
    assert_state_delta(before, _view(projects, project_id), UNIVERSE, expected, strict=True)


@given(data=st.data(), place_count=PLACE_COUNT, start_refused=st.booleans())
def test_a_place_of_another_project_as_an_anchor_is_refused_and_changes_nothing(
    data: st.DataObject, place_count: int, start_refused: bool
) -> None:
    anchors, projects, pois, project_id, ids = _catalog(place_count)
    anchors.set(project_id, ids[0], ids[-1])
    other = pois.add(projects.create("Dolomiti 2028").id, "Cortina", 46.5, 12.1).id
    place = data.draw(st.sampled_from(ids))
    start, end = (other, place) if start_refused else (place, other)
    before = _view(projects, project_id)

    with pytest.raises(AnchorNotAPlaceError):
        anchors.set(project_id, start, end)

    assert_state_delta(before, _view(projects, project_id), UNIVERSE, {}, strict=True)


@given(data=st.data(), place_count=PLACE_COUNT, unknown=st.uuids().map(lambda u: u.hex))
def test_an_unknown_project_or_item_is_not_found_and_changes_nothing(
    data: st.DataObject, place_count: int, unknown: str
) -> None:
    anchors, projects, _, project_id, ids = _catalog(place_count)
    place = data.draw(st.sampled_from(ids))
    target, start, end, error = data.draw(
        st.sampled_from(
            [
                (unknown, place, place, ProjectNotFoundError),
                (project_id, unknown, place, ItemNotFoundError),
                (project_id, place, unknown, ItemNotFoundError),
            ]
        )
    )
    before = _view(projects, project_id)

    with pytest.raises(error) as refused:
        anchors.set(target, start, end)

    assert_state_delta(before, _view(projects, project_id), UNIVERSE, {}, strict=True)
    named = f"No item with id {unknown}" if error is ItemNotFoundError else f"No project with id {unknown}"
    assert str(refused.value) == named, "the refusal names what was not found"


@given(place_count=PLACE_COUNT, track_count=st.integers(min_value=0, max_value=3), anchored=st.booleans())
def test_any_choice_is_exactly_the_new_anchors_or_is_refused_and_changes_nothing(
    place_count: int, track_count: int, anchored: bool
) -> None:
    # Every (start, end) pair over POIs, tracks, another project's place and None runs on every example (D212).
    catalog = InMemoryCatalog()
    projects = ProjectService(catalog.unit_of_work, FakeClock(datetime(2027, 6, 1, tzinfo=UTC)))
    pois, anchors = PoiService(catalog.unit_of_work), AnchorService(catalog.unit_of_work)
    project_id = projects.create("Alpi").id
    places = [pois.add(project_id, f"Place {i}", 45.0, 7.0).id for i in range(place_count)]
    tracks = [_add_track(catalog, project_id, i) for i in range(track_count)]
    foreign = pois.add(projects.create("Dolomiti").id, "Cortina", 46.5, 12.1).id
    if anchored:
        anchors.set(project_id, places[0], places[-1])
    for start in [*places, *tracks, foreign, None]:
        for end in [*places, *tracks, foreign, None]:
            before = _anchor_view(projects, project_id)
            if {start, end} <= {*places, None}:
                anchors.set(project_id, start, end)
                expected = {
                    "project.anchors": set_to((start, end)),
                    "project.revision": set_to(before["project.revision"] + 1),
                }
                if before["project.anchors"] == (start, end):
                    del expected["project.anchors"]
            else:
                with pytest.raises(AnchorNotAPlaceError, match=r"^Only places \(POIs\) can be the Start or End$"):
                    anchors.set(project_id, start, end)
                expected = {}
            after = _anchor_view(projects, project_id)
            assert_state_delta(before, after, {"project.anchors", "project.revision"}, expected, strict=True)


def _anchor_view(projects: ProjectService, project_id: str) -> dict[str, Any]:
    opened = projects.open(project_id)
    return {
        "project.anchors": (opened.anchors.start_item_id, opened.anchors.end_item_id),
        "project.revision": opened.revision,
    }


def _add_track(catalog: InMemoryCatalog, project_id: str, index: int) -> str:
    here = Coordinate(45.07, 7.69)
    track = TrackItem(
        id=f"track-{index}",
        project_id=project_id,
        name=f"Trail {index}",
        description=None,
        original_sha256="a",
        canonical_sha256="b",
        direction_version=1,
        point_count=2,
        entry=here,
        exit=here,
        length_m=1.0,
    )
    with catalog.unit_of_work() as uow:
        uow.items.add(track)
        uow.commit()
    return track.id
