"""The map's tile settings at `GET /api/config/map` (ADR-003 Amendment 2, ADR-004), through the real `create_app`.

Integration level: single examples verify wiring. The settings rules live in tests/unit/bootstrap/test_settings.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from overland_planner.bootstrap.app_factory import create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.common.workspace import workspace_data_dir

POSITRON = {
    "base_style_url": "https://tiles.openfreemap.org/styles/positron",
    "base_attribution": "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors",
}
KEYED = "https://tiles.example.test/{z}/{x}/{y}.png?access_token=not-a-real-token"


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def test_the_map_settings_answer_the_chosen_tiles_with_the_default_for_what_is_left_empty(data_dir: Path) -> None:
    environ = {"DATA_DIR": str(data_dir), "MAP_TILE_URL": "https://tiles.example.test/{z}/{x}/{y}.png"}
    with TestClient(create_app({**environ, "MAP_TILE_ATTRIBUTION": "", "MAP_TILE_MAX_ZOOM": "12"})) as client:
        answer = client.get("/api/config/map")
    assert answer.status_code == 200
    assert answer.json() == {
        "tile_url": "https://tiles.example.test/{z}/{x}/{y}.png",
        "attribution": "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
        "max_zoom": 12,
        **POSITRON,
        "road_map_area": "Italy, Spain, Switzerland, Austria and southern France",
    }


def test_the_light_base_map_is_chosen_by_the_settings_and_defaults_when_empty(data_dir: Path) -> None:
    chosen = {"MAP_BASE_STYLE_URL": "https://styles.example.test/light.json", "MAP_BASE_ATTRIBUTION": "Credit"}
    with TestClient(create_app({"DATA_DIR": str(data_dir), **chosen})) as client:
        answer = client.get("/api/config/map").json()
    assert (answer["base_style_url"], answer["base_attribution"]) == tuple(chosen.values())
    with TestClient(create_app({"DATA_DIR": str(data_dir), "MAP_BASE_STYLE_URL": ""})) as client:
        answer = client.get("/api/config/map").json()
    assert {k: answer[k] for k in POSITRON} == POSITRON


def test_the_road_map_area_is_the_default_and_can_be_set(data_dir: Path) -> None:
    with TestClient(create_app({"DATA_DIR": str(data_dir)})) as client:
        default = client.get("/api/config/map").json()["road_map_area"]
    with TestClient(create_app({"DATA_DIR": str(data_dir), "ROAD_MAP_AREA": "Spain"})) as client:
        chosen = client.get("/api/config/map").json()["road_map_area"]
    assert (default, chosen) == ("Italy, Spain, Switzerland, Austria and southern France", "Spain")


def test_the_map_settings_are_behind_the_household_password(data_dir: Path) -> None:
    environ = {"DATA_DIR": str(data_dir), "PLANNER_BASIC_AUTH_USER": "marco", "PLANNER_BASIC_AUTH_PASSWORD": "pw-1234"}
    with TestClient(create_app(environ)) as client:
        assert client.get("/api/config/map").status_code == 401
        assert client.get("/api/config/map", auth=("marco", "pw-1234")).status_code == 200


def test_a_keyed_tile_address_refuses_the_start_and_the_log_never_shows_the_key(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(StartupRefusedError):
        create_app({"DATA_DIR": str(data_dir), "MAP_TILE_URL": KEYED})

    out = capsys.readouterr().out
    (line,) = [json.loads(text) for text in out.splitlines()]
    assert (line["event"], line["component"]) == ("health.startup.refused", "settings")
    assert "MAP_TILE_URL" in line["reason"] and "access_token" in line["reason"]
    assert "not-a-real-token" not in out


def test_a_keyed_light_base_map_address_refuses_the_start_and_the_log_never_shows_the_key(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    keyed = "https://styles.example.test/light.json?api_key=not-a-real-key"
    with pytest.raises(StartupRefusedError):
        create_app({"DATA_DIR": str(data_dir), "MAP_BASE_STYLE_URL": keyed})

    out = capsys.readouterr().out
    (line,) = [json.loads(text) for text in out.splitlines()]
    assert "MAP_BASE_STYLE_URL" in line["reason"] and "api_key" in line["reason"]
    assert "not-a-real-key" not in out
