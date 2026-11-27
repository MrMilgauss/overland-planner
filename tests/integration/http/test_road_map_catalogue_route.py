"""`GET /api/road-map/catalogue` through the real `create_app` with the real catalogue adapter against a loopback
region service (D306, D308, D310): the wiring facts. Matching rules are the service's; the adapter's faults are in
tests/unit/adapters/roadmap."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from tests.acceptance.overland_route_planner_mvp.steps.road_map_fakes import (
    GB,
    RecordingServer,
    Seen,
    region_service,
)
from tests.common.workspace import workspace_data_dir

ROWS = {"key", "name", "parent_name", "bytes"}


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def planner(data_dir: Path, tmp_path: Path, server: RecordingServer, **ports: object) -> TestClient:
    (tmp_path / "changes").mkdir(exist_ok=True)
    environ = {
        "DATA_DIR": str(data_dir),
        "ROAD_MAP_DIR": str(tmp_path / "tilesets"),
        "ROAD_MAP_CHANGES_DIR": str(tmp_path / "changes"),
        "GEOFABRIK_INDEX_URL": f"{server.url}/index-v1-nogeom.json",
    }
    return TestClient(create_app(environ, external=ExternalPorts(**ports)))  # type: ignore[arg-type]


def test_a_search_finds_regions_with_their_parent_and_size(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    with planner(data_dir, tmp_path, server, catalogue_min_features=10) as client:
        answer = client.get("/api/road-map/catalogue", params={"q": "georgia"})
    server.stop()
    assert answer.status_code == 200
    assert sorted(answer.json()["results"], key=lambda row: row["key"]) == [
        {"key": "georgia", "name": "Georgia", "parent_name": "Europe", "bytes": int(0.03 * GB)},
        {"key": "us/georgia", "name": "Georgia", "parent_name": "United States of America", "bytes": int(0.5 * GB)},
    ]


@pytest.mark.parametrize("words", ["", "U", " u ", "  "])
def test_fewer_than_two_letters_is_refused_in_plain_words_and_sends_nothing(
    data_dir: Path, tmp_path: Path, words: str
) -> None:
    server = region_service()
    with planner(data_dir, tmp_path, server, catalogue_min_features=10) as client:
        before = len(server.requests("HEAD"))
        answer = client.get("/api/road-map/catalogue", params={"q": words})
    server.stop()
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_error")
    assert "two letters" in answer.json()["message"]
    assert len(server.requests("HEAD")) == before == 0


def test_at_most_eight_results_best_name_first(data_dir: Path, tmp_path: Path) -> None:
    holder: dict[str, RecordingServer] = {}

    def respond(seen: Seen) -> tuple[int, dict[str, str], bytes]:
        if seen.method == "HEAD":
            return 200, {"X-Length": "1000"}, b""
        base = holder["server"].url
        names = [f"Zone {n:02d}" for n in range(11)] + ["Zone", "Ozone"]
        features = [
            {
                "properties": {
                    "id": f"id-{name}",
                    "name": name,
                    "parent": None,
                    "urls": {"pbf": f"{base}/{name}-latest.osm.pbf", "poly": f"{base}/{name}.poly"},
                }
            }
            for name in names
        ]
        return 200, {}, json.dumps({"features": features}).encode()

    holder["server"] = server = RecordingServer(respond).start()
    with planner(data_dir, tmp_path, server, catalogue_min_features=1) as client:
        answer = client.get("/api/road-map/catalogue", params={"q": "zone"})
    server.stop()
    rows = answer.json()["results"]
    assert [row["name"] for row in rows] == ["Zone", *(f"Zone {n:02d}" for n in range(7))]
    assert set(rows[0]) == ROWS


def test_a_region_list_that_never_came_is_unavailable_and_the_health_says_so(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    server.stop()
    with planner(data_dir, tmp_path, server) as client:
        answer = client.get("/api/road-map/catalogue", params={"q": "utah"})
        health = client.get("/api/health")
    assert (answer.status_code, answer.json()["code"]) == (503, "region_catalogue_unavailable")
    assert "region_catalogue_unavailable" in health.text


def test_a_region_is_still_found_when_its_size_cannot_be_told(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    with planner(data_dir, tmp_path, server, catalogue_min_features=10) as client:
        client.get("/api/road-map/catalogue", params={"q": "ab"})  # the list is fetched and kept
    server.stop()
    with planner(data_dir, tmp_path, server, catalogue_min_features=10) as client:
        answer = client.get("/api/road-map/catalogue", params={"q": "utah"})
    assert answer.json()["results"] == [
        {"key": "us/utah", "name": "Utah", "parent_name": "United States of America", "bytes": None}
    ]
