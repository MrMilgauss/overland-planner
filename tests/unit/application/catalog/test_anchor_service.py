"""AnchorService (US-02c, HC-2, brief §5): Marco sets the Start and End of a trip among the project's POIs.

Driving ports: `AnchorService` with `PoiService` and `ProjectService` from the catalog facade. Driven port:
`CatalogUnitOfWork` (in-memory double honouring commit). Observable universe = what Marco sees through the driving
ports: `project.items` (name, type, anchor) and `project.revision` of the open project.
Test Budget: 3 behaviors (anchors replace the previous ones + revision, a refused anchor changes nothing, an unknown
project or item is not found) x 2 = 6; 3 used.
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

    with pytest.raises(error):
        anchors.set(target, start, end)

    assert_state_delta(before, _view(projects, project_id), UNIVERSE, {}, strict=True)
