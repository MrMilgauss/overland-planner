"""`GET /api/road-map` through the real `create_app` on a fixture volume (D308, D310): one example per wiring fact.

The matching rules live in the domain and the service; the reader's faults in tests/unit/adapters/roadmap.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
    body = answer.json()
    assert isinstance(body.pop("server_utc_offset_minutes"), int)
    assert body == {
        "served": {
            "known": True,
            "map_date": "2026-11-28T12:00:00Z",
            "regions": [{"key": "italy", "name": "Italy", "parent_name": None, "bytes": 5}],
            "total_bytes": 5,
        },
        "change": {
            "state": "none",
            "step": None,
            "steps_done": 0,
            "start_at": None,
            "added": [],
            "removed": [],
            "result": None,
        },
        "limits": {
            "changes_available": False,
            "max_gb": 8.0,
            "max_bytes": 8_000_000_000,
            "next_rebuild_from": None,
            "helper_seen_at": None,
            "rebuilds_set_up": False,
        },
        "planning_paused": False,
        "planning_back_at": None,
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


def _planner(data_dir: Path, tmp_path: Path, index_url: str, more: dict[str, str]) -> TestClient:
    if not (tmp_path / "changes").exists():
        (tmp_path / "changes").mkdir()
    if (tmp_path / "changes").is_dir():
        (tmp_path / "changes" / "helper-seen").touch()  # the helper of the Pi has just looked
    settings = (
        environ(data_dir, volume(tmp_path))
        | {"ROAD_MAP_CHANGES_DIR": str(tmp_path / "changes"), "GEOFABRIK_INDEX_URL": index_url}
        | more
    )
    return TestClient(create_app(settings, external=ExternalPorts(catalogue_min_features=10)))


def test_a_change_is_queued_shown_as_planned_and_cancelled(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    start = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with _planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json", {}) as client:
        before = client.get("/api/road-map").json()
        queued = client.post(
            "/api/road-map/change",
            json={"region_keys": ["italy", "portugal"], "start_at": start},
        )
        planned = client.get("/api/road-map").json()
        cancelled = client.delete("/api/road-map/change")
        after = client.get("/api/road-map").json()
        again = client.delete("/api/road-map/change")
    server.stop()
    assert queued.status_code == 201
    assert [r["key"] for r in queued.json()["added"]] == ["portugal"]
    assert before["limits"]["changes_available"] is True and before["limits"]["max_gb"] == 8.0
    assert before["limits"]["max_bytes"] == 8_000_000_000 and before["limits"]["rebuilds_set_up"] is True
    assert planned["served"] == before["served"]
    assert planned["change"]["state"] == "planned"
    assert planned["change"]["start_at"] == start
    assert [r["name"] for r in planned["change"]["added"]] == ["Portugal"]
    assert cancelled.status_code == 204
    assert after["change"]["state"] == "none"
    assert (again.status_code, again.json()["code"]) == (409, "change_not_pending")
    assert sorted(p.name for p in (tmp_path / "changes").iterdir()) == ["cancelled.txt", "helper-seen"]


def test_a_refused_change_answers_its_code_and_writes_nothing(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    with _planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json", {"ROAD_MAP_MAX_GB": "0.0001"}) as client:
        unknown = client.post("/api/road-map/change", json={"region_keys": ["atlantis"]})
        big = client.post("/api/road-map/change", json={"region_keys": ["portugal"]})
    server.stop()
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_region")
    assert (big.status_code, big.json()["code"]) == (422, "too_big")
    assert "0.4 GB" in big.json()["message"] and "limit is 0.0001 GB" in big.json()["message"]
    assert [p.name for p in (tmp_path / "changes").iterdir()] == ["helper-seen"]


def test_changes_that_cannot_be_kept_are_unavailable_everywhere(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    changes = tmp_path / "changes"
    changes.write_text("not a folder\n")
    with _planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json", {}) as client:
        view = client.get("/api/road-map").json()
        health = client.get("/api/health").json()
        refused = client.post("/api/road-map/change", json={"region_keys": ["italy", "portugal"]})
    server.stop()
    assert view["limits"]["changes_available"] is False
    assert health["components"]["road_map_changes"] == {
        "outcome": "degraded-healthy",
        "reason": "road_map_changes_unavailable",
    }
    assert (refused.status_code, refused.json()["code"]) == (503, "changes_unavailable")


def test_one_change_at_a_time_one_rebuild_a_day_a_start_in_its_window_and_refresh(
    data_dir: Path, tmp_path: Path
) -> None:
    server = region_service()
    now = datetime.now(UTC)
    day = now + timedelta(days=3)
    taken = day.strftime("%Y%m%d")
    (tmp_path / "tilesets").mkdir(exist_ok=True)
    with _planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json", {}) as client:
        (tmp_path / "tilesets" / taken).mkdir()  # a map of that day, the leftover of a failed switch
        same_day = client.post("/api/road-map/change", json={"region_keys": ["italy"], "start_at": day.isoformat()})
        too_soon = client.post(
            "/api/road-map/change",
            json={"region_keys": ["italy"], "start_at": (now + timedelta(minutes=1)).isoformat()},
        )
        refresh_cost = client.post("/api/road-map/change/preview", json={})
        refresh = client.post("/api/road-map/change", json={"start_at": (now + timedelta(days=5)).isoformat()})
        second = client.post("/api/road-map/change", json={"region_keys": ["italy", "portugal"]})
        (tmp_path / "changes" / "request.txt").rename(tmp_path / "changes" / "running.txt")
        third = client.post("/api/road-map/change", json={"region_keys": ["italy", "portugal"]})
        cancel = client.delete("/api/road-map/change")
    server.stop()
    midnight = (day + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    assert (same_day.status_code, same_day.json()["code"], same_day.json()["next_rebuild_from"]) == (
        422,
        "same_day",
        midnight,
    )
    assert (too_soon.status_code, too_soon.json()["code"]) == (422, "bad_start")
    assert refresh_cost.status_code == 200 and refresh_cost.json()["added"] == refresh_cost.json()["removed"] == []
    assert refresh.status_code == 201
    assert (second.status_code, second.json()["code"]) == (409, "change_pending")
    assert (third.status_code, third.json()["code"]) == (409, "rebuild_running")
    assert (cancel.status_code, cancel.json()["code"]) == (409, "change_not_pending")


def test_without_a_helper_the_change_is_refused_503_and_nothing_is_written(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    with _planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json", {}) as client:
        (tmp_path / "changes" / "helper-seen").unlink()
        view = client.get("/api/road-map").json()
        refused = client.post("/api/road-map/change", json={"region_keys": ["italy", "portugal"]})
    server.stop()
    assert (refused.status_code, refused.json()["code"]) == (503, "rebuilds_not_set_up")
    assert list((tmp_path / "changes").iterdir()) == []
    assert (view["limits"]["rebuilds_set_up"], view["limits"]["helper_seen_at"]) == (False, None)


def test_a_running_rebuild_shows_its_step_the_pause_and_when_planning_is_back(data_dir: Path, tmp_path: Path) -> None:
    server = region_service()
    began = datetime.now(UTC).replace(microsecond=0)
    with _planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json", {}) as client:
        client.post("/api/road-map/change", json={"region_keys": ["italy", "portugal"]})
        (tmp_path / "changes" / "request.txt").rename(tmp_path / "changes" / "running.txt")
        (tmp_path / "changes" / "progress.txt").write_text(f"step=building\nstep_at={int(began.timestamp())}\n")
        running = client.get("/api/road-map").json()
        (tmp_path / "changes" / "progress.txt").write_text("step=building\ncolour=red\n")
        unreadable = client.get("/api/road-map").json()
    server.stop()
    change = running["change"]
    assert (change["state"], change["step"], change["steps_done"]) == ("running", "building", 2)
    assert [r["name"] for r in change["added"]] == ["Portugal"]
    assert running["planning_paused"] is True
    assert datetime.fromisoformat(running["planning_back_at"]) > began
    assert running["limits"]["helper_seen_at"] is not None and "server_utc_offset_minutes" in running
    assert (unreadable["change"]["state"], unreadable["change"]["step"], unreadable["planning_paused"]) == (
        "running",
        None,
        False,
    )


def test_a_rebuild_that_stopped_for_lack_of_space_answers_failed_with_the_numbers_and_the_map_stays(
    data_dir: Path, tmp_path: Path
) -> None:
    server = region_service()
    with _planner(data_dir, tmp_path, f"{server.url}/index-v1-nogeom.json", {}) as client:
        client.post("/api/road-map/change", json={"region_keys": ["italy", "portugal"]})
        changes = tmp_path / "changes"
        ended = (changes / "request.txt").read_text() + "finished_at=1795950000\nstate=failed\ncode=disk\n"
        (changes / "request.txt").unlink()
        (changes / "result.txt").write_text(ended + "free_gb=18\nneed_gb=25\n")
        body = client.get("/api/road-map").json()
    server.stop()
    change = body["change"]
    assert change["state"] == "failed" and [r["name"] for r in change["added"]] == ["Portugal"]
    assert change["result"]["code"] == "disk"
    assert "the Pi has 18 GB of free disk and needs 25 GB" in change["result"]["message"]
    assert [r["name"] for r in body["served"]["regions"]] == ["Italy"]
