"""`GET /api/projects/{id}/coverage` through the real `create_app` on a fixture volume (D302, D308): one example per
wiring fact. The trip rules live in tests/unit/application/roadmap; the borders in the domain."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from overland_planner.bootstrap.app_factory import create_app
from tests.common.workspace import workspace_data_dir
from tests.integration.http.test_road_map_routes import environ, volume


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def trip_with_two_places(client: TestClient) -> tuple[str, str, str]:
    project = client.post("/api/projects", json={"name": "Trip"}).json()["id"]
    inside = client.post(f"/api/projects/{project}/pois", json={"name": "In", "lat": 0.5, "lon": 0.5}).json()["id"]
    outside = client.post(f"/api/projects/{project}/pois", json={"name": "Out", "lat": 5.0, "lon": 5.0}).json()["id"]
    return project, inside, outside


def test_a_place_beyond_the_served_border_is_listed_outside(data_dir: Path, tmp_path: Path) -> None:
    with TestClient(create_app(environ(data_dir, volume(tmp_path)))) as client:
        project, inside, outside = trip_with_two_places(client)
        answer = client.get(f"/api/projects/{project}/coverage")
    assert answer.status_code == 200
    assert answer.json() == {
        "known": True,
        "map_date": "2026-01-15T12:00:00Z",
        "regions": ["Italy"],
        "outside_item_ids": [outside],
        "groups": [{"regions": ["Italy"], "item_ids": [inside]}],
    }


def test_no_volume_is_an_unknown_coverage(data_dir: Path) -> None:
    with TestClient(create_app(environ(data_dir, None, served=""))) as client:
        project, _, _ = trip_with_two_places(client)
        answer = client.get(f"/api/projects/{project}/coverage")
    assert answer.json() == {"known": False, "map_date": None, "regions": [], "outside_item_ids": [], "groups": []}


def test_an_unknown_project_is_the_usual_not_found(data_dir: Path) -> None:
    with TestClient(create_app(environ(data_dir, None, served=""))) as client:
        answer = client.get("/api/projects/nope/coverage")
    assert answer.status_code == 404
    assert answer.json() == {"code": "not_found", "message": "Project not found"}
