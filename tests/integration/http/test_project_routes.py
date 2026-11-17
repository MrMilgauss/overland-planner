"""`PATCH /api/projects/{id}` through the real composition root (slice 06a, D249): the objective and the off-road speed.

Integration level: single examples verify the wiring (422 envelope, one revision per change, stored column); the rules
live in tests/unit/application/catalog/test_project_service.py.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from overland_planner.adapters.persistence.database import database_file
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from tests.common.solver_fakes import UnavailableTourSolver
from tests.common.workspace import workspace_data_dir


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def _planner(data_dir: Path) -> TestClient:
    return TestClient(
        create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=UnavailableTourSolver()))
    )


def _stored_objective(data_dir: Path, project_id: str) -> str:
    connection = sqlite3.connect(database_file(data_dir))
    (objective,) = connection.execute("SELECT objective FROM projects WHERE id = ?", (project_id,)).fetchone()
    connection.close()
    return str(objective)


def test_a_project_minimises_distance_until_its_objective_is_patched_and_the_change_is_one_revision(
    data_dir: Path,
) -> None:
    client = _planner(data_dir)
    created = client.post("/api/projects", json={"name": "Alpi"}).json()
    url = f"/api/projects/{created['id']}"
    assert (created["objective"], created["revision"]) == ("distance", 1)

    same = client.patch(url, json={"objective": "distance"})
    assert (same.status_code, same.json()["objective"], same.json()["revision"]) == (200, "distance", 1)

    both = client.patch(url, json={"objective": "time", "offroad_speed_kmh": 20})
    assert both.status_code == 200
    assert (both.json()["objective"], both.json()["offroad_speed_kmh"], both.json()["revision"]) == ("time", 20, 2)

    again = client.patch(url, json={"objective": "time", "offroad_speed_kmh": 20})
    assert (again.json()["revision"], _stored_objective(data_dir, created["id"])) == (2, "time")
    assert _planner(data_dir).get(url).json()["objective"] == "time", "read back by a new planner process"


@pytest.mark.parametrize(
    "body", [{}, {"objective": "fastest"}, {"objective": "fastest", "offroad_speed_kmh": 20}, {"objective": None}]
)
def test_an_empty_body_or_an_unknown_objective_answers_422_and_changes_nothing(
    data_dir: Path, body: dict[str, object]
) -> None:
    # bypass: four representative refusals of the same rule, one wiring each (envelope, nothing stored).
    client = _planner(data_dir)
    created = client.post("/api/projects", json={"name": "Alpi"}).json()
    url = f"/api/projects/{created['id']}"

    refused = client.patch(url, json=body)

    assert (refused.status_code, refused.json()["code"]) == (422, "validation_error")
    assert client.get(url).json() == created
