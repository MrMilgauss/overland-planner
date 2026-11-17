"""The road map is chosen by configuration and the planner starts whether or not the engine answers (D247).

Driving port: `create_app` with `ROUTING_PROVIDER=valhalla`, the real Valhalla adapter, and a scripted httpx transport
(the only fake: the engine is an external port, `ExternalPorts.routing_transport`). Integration level: single examples
verify wiring, not input invariants.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.common.fakes import FakeClock, FakeMountTable
from tests.common.workspace import workspace_data_dir
from tests.contract.routing_port.recordings import ScriptedEngine, recording

PROVIDER_ID = f"valhalla:3.9.1:{recording('status')['response']['tileset_last_modified']}"


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with workspace_data_dir("integration") as folder:
        yield folder


def _cell(metres_km: float, seconds: int) -> dict[str, Any]:
    return {"time": seconds, "distance": metres_km}


TORINO_SUSA = {
    "sources_to_targets": [[_cell(0, 0), _cell(52.4, 3200)], [_cell(53.1, 3300), _cell(0, 0)]],
}
WRONG_VERSION = {"version": "3.10.0", "tileset_last_modified": 1793560782}


def _start(
    data_dir: Path, engine: ScriptedEngine, capsys: pytest.CaptureFixture[str], **environ: str
) -> tuple[TestClient, list[dict[str, Any]]]:
    external = ExternalPorts(
        clock=FakeClock(), mount_table=FakeMountTable(), routing_transport=httpx.MockTransport(engine)
    )
    app = create_app({"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "valhalla", **environ}, external=external)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    return TestClient(app), lines


def _event(lines: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [line for line in lines if line.get("event") == name]


def test_an_engine_that_answers_is_an_ok_component_and_its_id_is_logged_at_start(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = ScriptedEngine(sources_to_targets=[httpx.Response(200, json=TORINO_SUSA)])

    client, lines = _start(data_dir, engine, capsys)

    assert client.get("/api/health").json()["components"]["routing_provider"] == {"outcome": "ok", "reason": None}
    assert _event(lines, "health.startup.degraded") == []
    (started,) = _event(lines, "app.started")
    assert (started["routing_provider"], started["routing_provider_id"]) == ("valhalla", PROVIDER_ID)


@pytest.mark.parametrize(
    ("engine", "reason", "known_id"),
    [
        pytest.param(
            ScriptedEngine(status=[httpx.ConnectError("refused")]), "routing_engine_unreachable", None, id="unreachable"
        ),
        pytest.param(
            ScriptedEngine(status=[httpx.Response(503)]), "routing_engine_not_ready", None, id="answering 5xx"
        ),
        pytest.param(
            ScriptedEngine(status=[httpx.Response(200, json=WRONG_VERSION)]),
            "routing_engine_version_mismatch: found 3.10.0, expected 3.9.1",
            None,
            id="another version",
        ),
    ],
)
def test_an_engine_that_is_down_or_of_another_version_degrades_the_start_and_never_refuses_it(
    data_dir: Path, capsys: pytest.CaptureFixture[str], engine: ScriptedEngine, reason: str, known_id: str | None
) -> None:
    client, lines = _start(data_dir, engine, capsys)

    assert client.get("/healthz").status_code == 200
    health = client.get("/api/health").json()
    assert health["components"]["routing_provider"] == {"outcome": "degraded-healthy", "reason": reason}
    assert [(line["component"], line["reason"]) for line in _event(lines, "health.startup.degraded")] == [
        ("routing_provider", reason)
    ]
    (started,) = _event(lines, "app.started")
    assert (started["routing_provider"], started["routing_provider_id"]) == ("valhalla", known_id)
    assert client.get("/api/projects").status_code == 200  # the catalog does not need the engine


def test_the_offline_road_map_stays_the_default_and_its_start_logs_no_engine_id(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(clock=FakeClock(), mount_table=FakeMountTable()))

    (started,) = _event([json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()], "app.started")
    assert started["routing_provider"] == "mock" and "routing_provider_id" not in started


def test_the_offline_script_with_the_engine_refuses_the_start_naming_mock_plan(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(StartupRefusedError) as refused:
        _start(data_dir, ScriptedEngine(), capsys, MOCK_PLAN=str(data_dir / "road-map.yaml"))

    assert (refused.value.code, refused.value.component) == (1, "settings")
    assert "MOCK_PLAN" in refused.value.reason
