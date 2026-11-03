"""The shared household password wired by the composition root (brief §12, ADR-011 Amendment 1, D98).

Integration level: single examples verify wiring (real uvicorn process for the switched-on case, so its log stream is
the real one); the credential invariants live in tests/unit/adapters/http/test_basic_auth_credentials.py.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.acceptance.overland_route_planner_mvp.steps.planner import ServerPlanner
from tests.common.fakes import FakeClock

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_ASSETS = REPO_ROOT / "web" / "dist" / "assets"
PROJECT = "Alpi Occidentali giugno 2027"


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """A workspace data folder, never the OS temp folder (ADR-011 D121)."""
    root = Path(os.environ.get("PLANNER_TEST_WORKSPACE", REPO_ROOT / ".data")) / "integration"
    folder = root / uuid.uuid4().hex[:12] / "data"
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(folder.parent, ignore_errors=True)


def test_with_the_password_on_everything_but_healthz_asks_to_log_in_and_the_password_is_never_logged(
    data_dir: Path,
) -> None:
    scripts = sorted(WEB_ASSETS.glob("*.js"))
    assert scripts, "no web build: run `make test-web` (or `make test`, which builds it first)"
    asset = f"/assets/{scripts[0].name}"
    password = "household-" + uuid.uuid4().hex[:8]
    planner = ServerPlanner(
        {
            "DATA_DIR": str(data_dir),
            "ROUTING_PROVIDER": "mock",
            "PLANNER_BASIC_AUTH_USER": "ferri",
            "PLANNER_BASIC_AUTH_PASSWORD": password,
        },
        workdir=REPO_ROOT,
    )
    try:
        planner.start()
        marco, stranger, wrong = (
            planner.session(("ferri", password)),
            planner.session(),
            planner.session(("ferri", password + "-wrong")),
        )
        assert marco.create_project(PROJECT).status_code == 201
        refused = {path: httpx.get(planner.base_url + path) for path in ("/", asset, "/api/health", "/api/projects")}
        refused["wrong"] = wrong.projects()
        admitted = {
            "asset": httpx.get(planner.base_url + asset, auth=("ferri", password)),
            "projects": marco.projects(),
        }
        health = stranger.health()
    finally:
        planner.stop()

    for path, answer in refused.items():
        assert answer.status_code == 401, path
        assert answer.headers["www-authenticate"].startswith('Basic realm="'), path
        assert PROJECT not in answer.text, path
    assert refused["/api/projects"].json()["code"] == "unauthorized"
    assert admitted["asset"].status_code == 200
    assert [p["name"] for p in admitted["projects"].json()] == [PROJECT]
    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    (record,) = planner.starts
    leaks = [line for line in record.stdout + record.stderr if password in line]
    assert leaks == [], f"the password appears in the log: {leaks}"
    (started,) = record.events("app.started")
    assert started["auth_enabled"] is True
    assert record.events("security.auth.disabled") == []


def test_with_the_password_off_each_start_logs_one_warning(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(clock=FakeClock()))

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    warnings = [line for line in lines if line["event"] == "security.auth.disabled"]
    assert [w["level"] for w in warnings] == ["warning"]
    (started,) = [line for line in lines if line["event"] == "app.started"]
    assert started["auth_enabled"] is False


def test_a_password_without_its_user_refuses_the_start(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    password = "household-" + uuid.uuid4().hex[:8]
    with pytest.raises(StartupRefusedError):
        create_app({"DATA_DIR": str(data_dir), "PLANNER_BASIC_AUTH_PASSWORD": password})

    out = capsys.readouterr().out
    assert [(line["event"], line["component"]) for line in map(json.loads, out.splitlines())] == [
        ("health.startup.refused", "settings")
    ]
    assert "PLANNER_BASIC_AUTH_USER" in out and password not in out
