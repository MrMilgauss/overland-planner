"""ProjectService (brief §3, §5; D151): create, list and open trip projects in one unit of work per use case.

Driving port: `ProjectService` from the catalog facade. Driven port: `CatalogUnitOfWork` (in-memory double in
`tests/common/catalog_fakes.py`, honouring commit/rollback like the SQLite adapter). Observable universe = what
Marco sees through the driving port: `projects.names` (the list) and `project.items` (the open project's items).
Test Budget: 8 behaviors (create+list, blank refused, open unknown refused, revision per change, removal clears the
anchors it held + revision, unknown or foreign item not removed, items listed by type, off-road speed taken or
refused) x 2 = 16; 8 used (the unknown-project test also covers setting the speed of an unknown project).
Removal universe = `project.items`, `project.anchors`, `project.revision` of the project and the same three of
another project (plan runs live outside the catalog and are covered by the acceptance scenarios).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import (
    AnchorService,
    ItemNotFoundError,
    PoiService,
    ProjectNotFoundError,
    ProjectService,
)
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.catalog.project import (
    NothingToChangeError,
    ObjectiveUnknownError,
    OffroadSpeedNotDrivableError,
    ProjectNameRequiredError,
)
from tests.common.catalog_fakes import InMemoryCatalog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"projects.names", "project.items"}
BLANK = st.text(alphabet=st.sampled_from([" ", "\t", "\n", chr(0xA0)]), max_size=8)
NAME = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")


def _service(existing: list[str] = []) -> ProjectService:  # noqa: B006 - read only
    service = ProjectService(InMemoryCatalog().unit_of_work, FakeClock(datetime(2027, 6, 1, tzinfo=UTC)))
    for name in existing:
        service.create(name)
    return service


def _view(service: ProjectService, open_id: str | None) -> dict[str, Any]:
    items = tuple(service.items(open_id)) if open_id is not None else ()
    return {"projects.names": tuple(sorted(p.name.value for p in service.list())), "project.items": items}


@given(existing=st.lists(NAME, max_size=3), name=NAME)
def test_a_named_project_is_created_listed_once_and_opens_empty_at_revision_one(existing: list[str], name: str) -> None:
    assume(name.strip() not in {e.strip() for e in existing})  # `gained` compares the listed names as a set
    service = _service(existing)
    before = _view(service, None)

    created = service.create(name)

    after = _view(service, created.id)
    assert_state_delta(before, after, UNIVERSE, {"projects.names": gained(name.strip())}, strict=True)
    opened = service.open(created.id)
    assert (opened.name.value, opened.revision) == (name.strip(), 1)
    assert [p.id for p in service.list()].count(created.id) == 1


@given(existing=st.lists(NAME, max_size=3), blank=BLANK)
def test_a_blank_name_creates_nothing(existing: list[str], blank: str) -> None:
    service = _service(existing)
    before = _view(service, None)

    with pytest.raises(ProjectNameRequiredError, match=r"^Give the project a name$"):
        service.create(blank)

    assert_state_delta(before, _view(service, None), UNIVERSE, {}, strict=True)


@given(existing=st.lists(NAME, max_size=3), unknown=st.uuids().map(lambda u: u.hex))
def test_an_unknown_project_id_is_not_found_and_changes_nothing(existing: list[str], unknown: str) -> None:
    service = _service(existing)
    before = _view(service, None)

    for use in (service.open, service.items, lambda project_id: service.set_offroad_speed(project_id, 20.0)):
        with pytest.raises(ProjectNotFoundError):
            use(unknown)

    assert_state_delta(before, _view(service, None), UNIVERSE, {}, strict=True)


def test_each_project_gets_its_own_id_and_creation_time() -> None:
    # bypass: wiring of the clock port and id uniqueness for two creations; one example covers it.
    service = _service()
    first, second = service.create("Alpi"), service.create("Alpi")
    assert first.id != second.id
    assert service.open(first.id).created_at == datetime(2027, 6, 1, tzinfo=UTC)


# --- removal and listing by type (slice 02, US-04 S2/S3) ----------------------------------------------------------
TRIP_UNIVERSE = {f"{p}.{slot}" for p in ("project", "other") for slot in ("items", "anchors", "revision")}
HERE = Coordinate(45.07, 7.69)


def _trip(catalog: InMemoryCatalog, project_id: str, kinds: list[str]) -> list[str]:
    """Adds one POI or track per kind, in order; the ids in the order added."""
    places = PoiService(catalog.unit_of_work)
    ids = []
    for index, kind in enumerate(kinds):
        if kind == "poi":
            ids.append(places.add(project_id, f"Place {index}", 45.0, 7.0).id)
            continue
        track = TrackItem(
            id=f"{project_id}-track-{index}",
            project_id=project_id,
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
        with catalog.unit_of_work() as uow:
            uow.items.add(track)
            uow.commit()
        ids.append(track.id)
    return ids


@st.composite
def trips(draw: st.DrawFn) -> tuple[ProjectService, str, str, list[str], list[str]]:
    """Two projects of POIs and tracks, each with any anchors among its POIs (or none)."""
    catalog = InMemoryCatalog()
    service = ProjectService(catalog.unit_of_work, FakeClock(datetime(2027, 6, 1, tzinfo=UTC)))
    anchors = AnchorService(catalog.unit_of_work)
    kinds = st.lists(st.sampled_from(["poi", "track"]), min_size=1, max_size=6)
    project_id, other_id = service.create("Alpi").id, service.create("Dolomiti").id
    ids, other_ids = _trip(catalog, project_id, draw(kinds)), _trip(catalog, other_id, draw(kinds))
    for trip in (project_id, other_id):
        places = [item.id for item in service.items(trip) if item.type == "poi"]
        choice = st.sampled_from([None, *places])
        start, end = draw(choice), draw(choice)
        if (start, end) != (None, None):
            anchors.set(trip, start, end)
    return service, project_id, other_id, ids, other_ids


def _trip_view(service: ProjectService, project_id: str, other_id: str) -> dict[str, Any]:
    view: dict[str, Any] = {}
    for prefix, trip in (("project", project_id), ("other", other_id)):
        opened = service.open(trip)
        view[f"{prefix}.items"] = tuple((item.id, item.type, item.anchor) for item in service.items(trip))
        view[f"{prefix}.anchors"] = (opened.anchors.start_item_id, opened.anchors.end_item_id)
        view[f"{prefix}.revision"] = opened.revision
    return view


@given(trip=trips(), data=st.data())
def test_removing_an_item_drops_its_row_clears_the_anchors_it_held_and_adds_one_revision(
    trip: tuple[ProjectService, str, str, list[str], list[str]], data: st.DataObject
) -> None:
    service, project_id, other_id, ids, _ = trip
    removed = data.draw(st.sampled_from(ids))
    before = _trip_view(service, project_id, other_id)

    service.remove_item(project_id, removed)

    start, end = before["project.anchors"]
    anchors = (None if start == removed else start, None if end == removed else end)
    expected = {
        "project.items": set_to(tuple(row for row in before["project.items"] if row[0] != removed)),
        "project.revision": set_to(before["project.revision"] + 1),
    }
    if anchors != before["project.anchors"]:
        expected["project.anchors"] = set_to(anchors)
    assert_state_delta(before, _trip_view(service, project_id, other_id), TRIP_UNIVERSE, expected, strict=True)


@given(trip=trips(), data=st.data(), unknown=st.uuids().map(lambda u: u.hex))
def test_an_unknown_item_or_an_item_of_another_project_is_not_removed_and_nothing_changes(
    trip: tuple[ProjectService, str, str, list[str], list[str]], data: st.DataObject, unknown: str
) -> None:
    service, project_id, other_id, ids, other_ids = trip
    before = _trip_view(service, project_id, other_id)
    # Every refused case runs on every example (D212).
    cases = [(project_id, unknown, ItemNotFoundError), (unknown, ids[0], ProjectNotFoundError)]
    cases += [(project_id, foreign, ItemNotFoundError) for foreign in other_ids]
    for target, item_id, error in cases:
        with pytest.raises(error) as refused:
            service.remove_item(target, item_id)
        named = f"No item with id {item_id}" if error is ItemNotFoundError else f"No project with id {target}"
        assert str(refused.value) == named, "the refusal names what was not found"

    assert_state_delta(before, _trip_view(service, project_id, other_id), TRIP_UNIVERSE, {}, strict=True)


@given(trip=trips())
def test_items_of_a_type_are_the_items_of_that_type_in_the_order_added(
    trip: tuple[ProjectService, str, str, list[str], list[str]],
) -> None:
    # bypass: a read changes nothing; the listing itself is the outcome, compared with the full list.
    service, project_id, _, _, _ = trip
    every = [(item.id, item.type, item.anchor) for item in service.items(project_id)]
    for item_type in ("poi", "track"):
        listed = [(item.id, item.type, item.anchor) for item in service.items(project_id, item_type)]
        assert listed == [row for row in every if row[1] == item_type]
    assert [item.id for item in service.items(project_id, None)] == [row[0] for row in every]


# --- off-road speed (slice 02, US-05 S4, FR-4.6) ------------------------------------------------------------------
SPEED_UNIVERSE = {"project.offroad_speed_kmh", "project.revision", "project.items", "project.anchors"}
DRIVABLE = st.floats(min_value=0, exclude_min=True, allow_infinity=False, allow_subnormal=True)
NOT_DRIVABLE = st.one_of(st.floats(max_value=0), st.sampled_from([float("nan"), float("inf"), float("-inf")]))


def _speed_view(service: ProjectService, project_id: str) -> dict[str, Any]:
    opened = service.open(project_id)
    return {
        "project.offroad_speed_kmh": opened.offroad_speed.kmh,
        "project.revision": opened.revision,
        "project.items": tuple((item.id, item.type, item.anchor) for item in service.items(project_id)),
        "project.anchors": (opened.anchors.start_item_id, opened.anchors.end_item_id),
    }


@given(trip=trips(), refused=NOT_DRIVABLE, taken=DRIVABLE)
@example(trip=None, refused=0.0, taken=5e-324).via("boundary")
@example(trip=None, refused=-0.0, taken=1e308).via("boundary")
@example(trip=None, refused=float("nan"), taken=15.0).via("boundary")
@example(trip=None, refused=float("inf"), taken=0.1).via("boundary")
@example(trip=None, refused=float("-inf"), taken=120.0).via("boundary")
def test_a_drivable_speed_is_taken_with_one_revision_and_any_other_is_refused_changing_nothing(
    trip: tuple[ProjectService, str, str, list[str], list[str]] | None, refused: float, taken: float
) -> None:
    # Every example runs both rules (D212): first a refused speed, then a drivable one.
    service, project_id = (_service(), None) if trip is None else (trip[0], trip[1])
    project_id = project_id or service.create("Alpi").id
    before = _speed_view(service, project_id)
    assert before["project.offroad_speed_kmh"] == 15  # FR-4.6 default

    with pytest.raises(OffroadSpeedNotDrivableError, match=r"^Off-road speed must be more than 0 km/h$"):
        service.set_offroad_speed(project_id, refused)
    assert_state_delta(before, _speed_view(service, project_id), SPEED_UNIVERSE, {}, strict=True)

    changed = service.set_offroad_speed(project_id, taken)

    expected = {
        "project.offroad_speed_kmh": set_to(taken),
        "project.revision": set_to(before["project.revision"] + 1),
    }
    assert_state_delta(before, _speed_view(service, project_id), SPEED_UNIVERSE, expected, strict=True)
    assert (changed.offroad_speed.kmh, changed.revision) == (taken, before["project.revision"] + 1)


# --- objective (slice 06a, D249) ----------------------------------------------------------------------------------
SETTINGS_UNIVERSE = SPEED_UNIVERSE | {"project.objective"}


def _settings_view(service: ProjectService, project_id: str) -> dict[str, Any]:
    return {**_speed_view(service, project_id), "project.objective": service.open(project_id).objective.value}


@given(objective=st.sampled_from([None, "distance", "time"]), speed=st.sampled_from([None, 15.0, 22.5]))
def test_settings_are_taken_in_one_revision_and_the_same_values_change_nothing(
    objective: str | None, speed: float | None
) -> None:
    service = _service()
    project_id = service.create("Alpi").id
    before = _settings_view(service, project_id)
    assert (before["project.objective"], before["project.offroad_speed_kmh"]) == ("distance", 15)  # the defaults

    if objective is None and speed is None:
        with pytest.raises(NothingToChangeError):
            service.update_settings(project_id, objective, speed)
        assert_state_delta(before, _settings_view(service, project_id), SETTINGS_UNIVERSE, {}, strict=True)
        return
    service.update_settings(project_id, objective, speed)

    differs = objective not in (None, "distance") or speed not in (None, 15.0)
    expected = {
        "project.objective": set_to(objective or "distance"),
        "project.offroad_speed_kmh": set_to(speed or 15.0),
        "project.revision": set_to(before["project.revision"] + differs),
    }
    assert_state_delta(before, _settings_view(service, project_id), SETTINGS_UNIVERSE, expected, strict=True)


@given(unknown=st.text(max_size=12).filter(lambda text: text not in ("distance", "time")), speed=DRIVABLE)
def test_an_unknown_objective_is_refused_and_even_a_drivable_speed_beside_it_changes_nothing(
    unknown: str, speed: float
) -> None:
    service = _service()
    project_id = service.create("Alpi").id
    before = _settings_view(service, project_id)

    with pytest.raises(ObjectiveUnknownError):
        service.update_settings(project_id, unknown, speed)

    assert_state_delta(before, _settings_view(service, project_id), SETTINGS_UNIVERSE, {}, strict=True)
