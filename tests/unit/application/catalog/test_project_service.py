"""ProjectService (brief §3, §5; D151): create, list and open trip projects in one unit of work per use case.

Driving port: `ProjectService` from the catalog facade. Driven port: `CatalogUnitOfWork` (in-memory double in
`tests/common/catalog_fakes.py`, honouring commit/rollback like the SQLite adapter). Observable universe = what
Marco sees through the driving port: `projects.names` (the list) and `project.items` (the open project's items).
Test Budget: 4 behaviors (create+list, blank refused, open unknown refused, revision per change) x 2 = 8; 4 used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from overland_planner.application.catalog.facade import ProjectNotFoundError, ProjectService
from overland_planner.domain.catalog.project import ProjectNameRequiredError
from tests.common.catalog_fakes import InMemoryCatalog
from tests.common.fakes import FakeClock
from tests.common.predicates import gained
from tests.common.state_delta import assert_state_delta

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

    for use in (service.open, service.items):
        with pytest.raises(ProjectNotFoundError):
            use(unknown)

    assert_state_delta(before, _view(service, None), UNIVERSE, {}, strict=True)


def test_each_project_gets_its_own_id_and_creation_time() -> None:
    # bypass: wiring of the clock port and id uniqueness for two creations; one example covers it.
    service = _service()
    first, second = service.create("Alpi"), service.create("Alpi")
    assert first.id != second.id
    assert service.open(first.id).created_at == datetime(2027, 6, 1, tzinfo=UTC)
