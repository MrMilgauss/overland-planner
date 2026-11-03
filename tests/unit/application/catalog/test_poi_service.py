"""PoiService (US-02c, brief §3, §5): a named place added by decimal degrees becomes an included POI of the project.

Driving port: `PoiService` from the catalog facade (with `ProjectService` to create and open projects). Driven port:
`CatalogUnitOfWork` (in-memory double honouring commit). Observable universe = what Marco sees through the driving
ports: `project.items` (type, name, included, anchor, location) and `project.revision` of the open project.
Test Budget: 3 behaviors (POI added + revision, refused name/coordinates add nothing, unknown project) x 2 = 6; 3 used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import PoiService, ProjectNotFoundError, ProjectService
from overland_planner.domain.catalog.coordinate import CoordinateOutOfRangeError
from overland_planner.domain.catalog.poi import PoiNameRequiredError
from tests.common.catalog_fakes import InMemoryCatalog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"project.items", "project.revision"}
NAME = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")
BLANK = st.text(alphabet=st.sampled_from([" ", "\t", "\n", chr(0xA0)]), max_size=8)
LATITUDE = st.floats(min_value=-90.0, max_value=90.0)
LONGITUDE = st.floats(min_value=-180.0, max_value=180.0)
PLACE = st.tuples(NAME, LATITUDE, LONGITUDE)
OUTSIDE_LATITUDE = st.floats(min_value=90.0, exclude_min=True) | st.floats(max_value=-90.0, exclude_max=True)
OUTSIDE_LONGITUDE = st.floats(min_value=180.0, exclude_min=True) | st.floats(max_value=-180.0, exclude_max=True)


def _project(existing: list[tuple[str, float, float]]) -> tuple[PoiService, ProjectService, str]:
    catalog = InMemoryCatalog()
    projects = ProjectService(catalog.unit_of_work, FakeClock(datetime(2027, 6, 1, tzinfo=UTC)))
    pois = PoiService(catalog.unit_of_work)
    project_id = projects.create("Alpi Occidentali giugno 2027").id
    for name, latitude, longitude in existing:
        pois.add(project_id, name, latitude, longitude)
    return pois, projects, project_id


def _row(item: Any) -> tuple[Any, ...]:
    return (item.type, item.name, item.included, item.anchor, (item.location.latitude, item.location.longitude))


def _view(projects: ProjectService, project_id: str) -> dict[str, Any]:
    return {
        "project.items": tuple(_row(item) for item in projects.items(project_id)),
        "project.revision": projects.open(project_id).revision,
    }


@given(existing=st.lists(PLACE, max_size=3), place=PLACE)
@example(existing=[], place=("North edge", 90.0, 180.0))
@example(existing=[], place=("South edge", -90.0, -180.0))
def test_an_added_place_is_one_more_included_poi_and_one_more_revision(
    existing: list[tuple[str, float, float]], place: tuple[str, float, float]
) -> None:
    name, latitude, longitude = place
    new_row = ("poi", name.strip(), True, None, (latitude, longitude))
    pois, projects, project_id = _project(existing)
    before = _view(projects, project_id)
    assume(new_row not in before["project.items"])  # `gained` compares the rows as a set

    added = pois.add(project_id, name, latitude, longitude)

    expected = {"project.items": gained(new_row), "project.revision": set_to(before["project.revision"] + 1)}
    assert_state_delta(before, _view(projects, project_id), UNIVERSE, expected, strict=True)
    assert _view(projects, project_id)["project.items"][-1] == new_row  # listed after the earlier items
    ids = [item.id for item in projects.items(project_id)]
    assert ids[-1] == added.id and len(set(ids)) == len(ids)  # the answer names the listed POI; ids never repeat


@given(
    existing=st.lists(PLACE, max_size=3),
    refused=st.one_of(
        st.tuples(BLANK, LATITUDE, LONGITUDE, st.just((PoiNameRequiredError, "Give the place a name"))),
        st.tuples(
            NAME,
            OUTSIDE_LATITUDE | st.just(float("nan")),
            LONGITUDE | OUTSIDE_LONGITUDE,
            st.just((CoordinateOutOfRangeError, "Latitude must be between -90 and 90")),
        ),
        st.tuples(
            NAME,
            LATITUDE,
            OUTSIDE_LONGITUDE | st.just(float("nan")),
            st.just((CoordinateOutOfRangeError, "Longitude must be between -180 and 180")),
        ),
    ),
)
def test_a_blank_name_or_out_of_range_coordinates_add_nothing(
    existing: list[tuple[str, float, float]], refused: tuple[str, float, float, tuple[type[Exception], str]]
) -> None:
    name, latitude, longitude, (error, reason) = refused
    pois, projects, project_id = _project(existing)
    before = _view(projects, project_id)

    with pytest.raises(error) as refusal:
        pois.add(project_id, name, latitude, longitude)

    assert str(refusal.value) == reason
    assert_state_delta(before, _view(projects, project_id), UNIVERSE, {}, strict=True)


@given(existing=st.lists(PLACE, max_size=3), place=PLACE, unknown=st.uuids().map(lambda u: u.hex))
def test_a_place_for_an_unknown_project_is_not_found_and_changes_nothing(
    existing: list[tuple[str, float, float]], place: tuple[str, float, float], unknown: str
) -> None:
    pois, projects, project_id = _project(existing)
    before = _view(projects, project_id)

    with pytest.raises(ProjectNotFoundError):
        pois.add(unknown, *place)

    assert_state_delta(before, _view(projects, project_id), UNIVERSE, {}, strict=True)
