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
    }


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
