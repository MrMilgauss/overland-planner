"""`GET /api/road-map` through the real `create_app` on a fixture volume (D308, D310): one example per wiring fact.

The matching rules live in the domain and the service; the reader's faults in tests/unit/adapters/roadmap.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.acceptance.overland_route_planner_mvp.steps.road_map_fakes import region_service
from tests.common.workspace import workspace_data_dir

SQUARE = "square\n1\n 0.0 0.0\n 0.0 1.0\n 1.0 1.0\n 1.0 0.0\nEND\nEND\n"
BUILT = 1_795_867_200  # 2026-11-28 12:00 UTC


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def volume(root: Path, border: str = SQUARE) -> Path:
    base = root / "tilesets"
    folder = base / "20261128"
    (folder / "outlines").mkdir(parents=True)
    record = {
        "schema": 1,
        "regions": [
            {"key": "italy", "name": "Italy", "parent_name": None, "pbf_url": "u", "outline": "italy.poly", "bytes": 5}
        ],
    }
    (folder / "road-map.json").write_text(json.dumps(record))
    (folder / "outlines" / "italy.poly").write_text(border)
    os.utime(folder / "road-map.json", (BUILT, BUILT))
    return base


def environ(data_dir: Path, base: Path | None, served: str = "20261128") -> dict[str, str]:
    return {
        "DATA_DIR": str(data_dir),
        "ROAD_MAP_DIR": "" if base is None else str(base),
        "ROAD_MAP_SERVED_TILESET": served,
    }


def test_the_served_map_is_named_with_its_regions_and_its_date(data_dir: Path, tmp_path: Path) -> None:
    with TestClient(create_app(environ(data_dir, volume(tmp_path)))) as client:
        answer = client.get("/api/road-map")
    assert answer.status_code == 200
    assert answer.json() == {
        "served": {
            "known": True,
            "map_date": "2026-11-28T12:00:00Z",
            "regions": [{"key": "italy", "name": "Italy", "parent_name": None, "bytes": 5}],
            "total_bytes": 5,
        },
        "change": {"state": "none"},
    }


def test_no_volume_is_an_unknown_map_and_a_healthy_planner(data_dir: Path) -> None:
    with TestClient(create_app(environ(data_dir, None, served=""))) as client:
        served = client.get("/api/road-map").json()["served"]
        health = client.get("/api/health").json()
    assert served == {"known": False, "map_date": None, "regions": [], "total_bytes": 0}
    assert health["components"]["tileset_store"] == {"outcome": "ok", "reason": None}


def test_a_damaged_border_degrades_the_component_and_the_map_stays_unknown(data_dir: Path, tmp_path: Path) -> None:
    with TestClient(create_app(environ(data_dir, volume(tmp_path, border="nonsense")))) as client:
        served = client.get("/api/road-map").json()["served"]
        health = client.get("/api/health").json()
    assert served["known"] is False and served["regions"] == []
    assert health["components"]["tileset_store"] == {"outcome": "degraded-healthy", "reason": "road_map_unreadable"}


def test_a_served_tileset_with_the_valhalla_provider_refuses_the_start_naming_the_key(data_dir: Path) -> None:
    with pytest.raises(StartupRefusedError) as refused:
        create_app({"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "valhalla", "ROAD_MAP_SERVED_TILESET": "20261128"})
    assert "ROAD_MAP_SERVED_TILESET" in refused.value.reason


def preview_planner(data_dir: Path, tmp_path: Path, index_url: str) -> TestClient:
    (tmp_path / "changes").mkdir(exist_ok=True)
    settings = environ(data_dir, volume(tmp_path)) | {
        "ROAD_MAP_CHANGES_DIR": str(tmp_path / "changes"),
        "GEOFABRIK_INDEX_URL": index_url,
    }
    return TestClient(create_app(settings, external=ExternalPorts(catalogue_min_features=10)))


def test_a_change_is_summarised_with_the_figures_and_writes_nothing(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    with preview_planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json") as client:
        answer = client.post(
            "/api/road-map/change/preview", json={"region_keys": ["italy", "portugal"], "start_at": None}
        )
        unknown = client.post("/api/road-map/change/preview", json={"region_keys": ["atlantis"]})
    server.stop()
    body = answer.json()
    assert answer.status_code == 200
    assert (body["added"], body["removed"]) == ([{"key": "portugal", "name": "Portugal"}], [])
    assert set(body["estimate"]) == {"total_minutes", "pause_minutes"}
    assert body["total_bytes"] > 5  # the served square is far from Portugal: information, status 200
    assert [g["regions"] for g in body["land_groups"]] == [["Italy"], ["Portugal"]]
    assert "Portugal" in body["not_linked_note"]
    assert list((tmp_path / "changes").iterdir()) == []
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_region")


def test_a_summary_without_the_list_of_regions_is_unavailable(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    server.stop()
    with preview_planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json") as client:
        answer = client.post("/api/road-map/change/preview", json={"region_keys": ["italy"]})
    assert (answer.status_code, answer.json()["code"]) == (503, "region_catalogue_unavailable")
