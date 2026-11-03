"""Health endpoints and the built web page, wired by the composition root (ADR-011, brief §5 and §7, D108, D162).

Integration level: single examples verify wiring (real uvicorn process, `create_app` over HTTP), not invariants;
the aggregation invariants live in tests/unit/application/platform/test_health_service.py.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from tests.acceptance.overland_route_planner_mvp.steps.planner import ServerPlanner
from tests.common.fakes import FakeClock, FakeMountTable

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILT_WEB_PAGE = REPO_ROOT / "web" / "dist" / "index.html"
NOT_PERSISTENT = "Data directory is not persistent - projects would be lost on restart"


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """A workspace data folder, never the OS temp folder (ADR-011 D121)."""
    root = Path(os.environ.get("PLANNER_TEST_WORKSPACE", REPO_ROOT / ".data")) / "integration"
    folder = root / uuid.uuid4().hex[:12] / "data"
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(folder.parent, ignore_errors=True)


class _UnhealthyClock(FakeClock):
    """A component whose start-up probe reports degraded-unhealthy (stands in for e.g. the persistence probe)."""

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="degraded-unhealthy", reason=NOT_PERSISTENT)


def _client(environ: dict[str, str], external: ExternalPorts | None = None) -> TestClient:
    return TestClient(
        create_app(environ, external=external or ExternalPorts(clock=FakeClock(), mount_table=FakeMountTable()))
    )


def test_server_answers_healthz_after_start_up_line(data_dir: Path) -> None:
    planner = ServerPlanner({"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock"}, workdir=REPO_ROOT)
    try:
        planner.start()
        health = planner.session().health()
        assert (health.status_code, health.json()) == (200, {"status": "ok"})
    finally:
        planner.stop()

    (record,) = planner.starts
    events = [line["event"] for line in record.json_lines()]
    assert events.count("app.started") == 1, record.tail()
    assert all(isinstance(json.loads(line), dict) for line in record.stdout), "stdout must hold only JSON lines"


def test_home_page_is_the_built_web_page(data_dir: Path) -> None:
    assert BUILT_WEB_PAGE.is_file(), "no web build: run `make test-web` (or `make test`, which builds it first)"

    page = _client({"DATA_DIR": str(data_dir)}).get("/")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.text == BUILT_WEB_PAGE.read_text()


def test_without_a_web_build_the_home_page_is_not_found(data_dir: Path, tmp_path: Path) -> None:
    page = _client({"DATA_DIR": str(data_dir), "WEB_DIST_DIR": str(tmp_path)}).get("/")

    assert page.status_code == 404
    assert not page.headers["content-type"].startswith("text/html")


def test_api_health_lists_component_outcomes(data_dir: Path) -> None:
    detail = _client({"DATA_DIR": str(data_dir)}).get("/api/health")

    assert (detail.status_code, detail.json()) == (
        200,
        {
            "status": "ok",
            "components": {
                "clock": {"outcome": "ok", "reason": None},
                "data_dir": {"outcome": "ok", "reason": None},
                "database": {"outcome": "ok", "reason": None},
                "event_log": {"outcome": "ok", "reason": None},
                "file_store": {"outcome": "ok", "reason": None},
                "gpx_parser": {"outcome": "ok", "reason": None},
                "mount_table": {"outcome": "ok", "reason": None},
                "tour_solver": {"outcome": "ok", "reason": None},
            },
            "banners": [],
        },
    )


def test_a_degraded_unhealthy_component_makes_healthz_503_with_its_reason_and_a_banner(data_dir: Path) -> None:
    client = _client({"DATA_DIR": str(data_dir)}, ExternalPorts(clock=_UnhealthyClock(), mount_table=FakeMountTable()))

    health = client.get("/healthz")
    detail = client.get("/api/health").json()

    assert (health.status_code, health.json()) == (503, {"status": "unhealthy", "reason": NOT_PERSISTENT})
    assert (detail["status"], detail["banners"]) == ("unhealthy", [NOT_PERSISTENT])
    assert detail["components"]["clock"] == {"outcome": "degraded-unhealthy", "reason": NOT_PERSISTENT}


def test_a_data_dir_symlinked_onto_tmpfs_is_reported_not_persistent(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ram_disk = data_dir / "ram"
    ram_disk.mkdir()
    (data_dir / "link").symlink_to(ram_disk)
    tables = ExternalPorts(clock=FakeClock(), mount_table=FakeMountTable.with_mount(ram_disk, "tmpfs"))

    client = _client({"DATA_DIR": str(data_dir / "link")}, tables)

    assert (client.get("/healthz").status_code, client.get("/api/health").json()["banners"]) == (503, [NOT_PERSISTENT])
    degraded = [json.loads(line) for line in capsys.readouterr().out.splitlines() if "health.startup.degraded" in line]
    assert [(line["component"], line["reason"]) for line in degraded] == [("data_dir", "data_dir_not_persistent")]


def test_a_refused_start_exits_non_zero_after_one_refusal_line_and_answers_nothing(data_dir: Path) -> None:
    planner = ServerPlanner({"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "valhalla"}, workdir=REPO_ROOT)

    record = planner.launch()
    planner.stop()

    assert not record.answered
    assert record.exit_code not in (None, 0), record.tail()
    assert [(line["event"], line["component"]) for line in record.json_lines()] == [
        ("health.startup.refused", "settings")
    ], record.tail()
    assert "ROUTING_PROVIDER" in record.json_lines()[0]["reason"]
    assert len(record.stdout) == 1, "stdout must hold only the refusal line"
