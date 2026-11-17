"""Health endpoints and the built web page, wired by the composition root (ADR-011, brief §5 and §7, D108, D162).

Integration level: single examples verify wiring (real uvicorn process, `create_app` over HTTP), not invariants;
the aggregation invariants live in tests/unit/application/platform/test_health_service.py.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from overland_planner.adapters.persistence.database import SqliteDatabase
from overland_planner.adapters.persistence.planning_unit_of_work import SqlAlchemyPlanningUnitOfWork
from overland_planner.adapters.persistence.tables import plan_runs
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tour_solver import TourNoRoute
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from overland_planner.domain.catalog.item import TrackItem
from overland_planner.domain.planning.plan_run import PlanStop
from tests.acceptance.overland_route_planner_mvp.steps.places import trail_file_bytes
from tests.acceptance.overland_route_planner_mvp.steps.planner import ServerPlanner
from tests.common.catalog_fakes import RecordingEventLog
from tests.common.fakes import FakeClock, FakeMountTable
from tests.common.workspace import workspace_data_dir
from tests.unit.application.planning.scripted_tour_solver import Script, ScriptedTourSolver

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILT_WEB_PAGE = REPO_ROOT / "web" / "dist" / "index.html"
NOT_PERSISTENT = "Data directory is not persistent - projects would be lost on restart"
PLAN_DEADLINE_S = 30.0
ASSIETTA = "Strada dell'Assietta"
COLUMNS = ("leg_s", "track_km", "offroad_s", "cumulative_km", "cumulative_s")
LEVEL_KEYS = ("confidence", "reason", "leg_confidence", "leg_reason")  # 07-06
SHOWN_STOP_KEYS = {"name", "type", "leg_km", "entry", "exit", *COLUMNS, *LEVEL_KEYS}
STORED_STOP_KEYS = {
    *LEVEL_KEYS,
    "retrace_sha256",
    "item_id",
    "name",
    "kind",
    "leg_km",
    "location",
    "entry",
    "exit",
    "direction_version",
    "point_count",
    "canonical_sha256",
    *COLUMNS,
}


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """A workspace data folder, never the OS temp folder (ADR-011 D121)."""
    with workspace_data_dir("integration") as folder:
        yield folder


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
                "diagnostics_reader": {"outcome": "ok", "reason": None},
                "event_log": {"outcome": "ok", "reason": None},
                "file_store": {"outcome": "ok", "reason": None},
                "gpx_parser": {"outcome": "ok", "reason": None},
                "gpx_writer": {"outcome": "ok", "reason": None},
                "mount_table": {"outcome": "ok", "reason": None},
                "plan_job_log": {"outcome": "ok", "reason": None},
                "plan_refusal_log": {"outcome": "ok", "reason": None},
                "routing_provider": {"outcome": "ok", "reason": None},
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
    planner = ServerPlanner({"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "osrm"}, workdir=REPO_ROOT)

    record = planner.launch()
    planner.stop()

    assert not record.answered
    assert record.exit_code not in (None, 0), record.tail()
    assert [(line["event"], line["component"]) for line in record.json_lines()] == [
        ("health.startup.refused", "settings")
    ], record.tail()
    assert "ROUTING_PROVIDER" in record.json_lines()[0]["reason"]
    assert len(record.stdout) == 1, "stdout must hold only the refusal line"


def test_a_missing_road_map_file_refuses_the_start_with_one_routing_provider_line(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    road_map = data_dir / "no-such-road-map.yaml"

    with pytest.raises(StartupRefusedError):
        _client({"DATA_DIR": str(data_dir), "MOCK_PLAN": str(road_map)})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    refused = [line for line in lines if line["event"] == "health.startup.refused"]
    assert [line["component"] for line in refused] == ["routing_provider"]
    assert str(road_map) in refused[0]["reason"]
    assert "app.started" not in [line["event"] for line in lines]


def _project_with_a_trail_between_two_places(client: TestClient) -> tuple[str, dict[str, str]]:
    """Added in the order Briancon, the Assietta, Casa Marco; Casa Marco is Start and End."""
    project_id = client.post("/api/projects", json={"name": "Stored plan"}).json()["id"]
    places = f"/api/projects/{project_id}/pois"
    client.post(places, json={"name": "Briancon", "lat": 44.8986, "lon": 6.6419}).raise_for_status()
    files = [("files", ("assietta.gpx", trail_file_bytes("assietta.gpx"), "application/gpx+xml"))]
    client.post(f"/api/projects/{project_id}/tracks", files=files).raise_for_status()
    home = client.post(places, json={"name": "Casa Marco", "lat": 45.0703, "lon": 7.6869}).json()["id"]
    anchors = {"start_item_id": home, "end_item_id": home}
    client.put(f"/api/projects/{project_id}/anchors", json=anchors).raise_for_status()
    items = client.get(f"/api/projects/{project_id}/items").json()
    return project_id, {item["name"]: item["id"] for item in items}


def _plan(client: TestClient, project_id: str) -> dict[str, object]:
    return _plan_job(client, project_id)[1]


def _plan_job(client: TestClient, project_id: str) -> tuple[str, dict[str, object]]:
    """The ended job's id and its last poll."""
    accepted = client.post(f"/api/projects/{project_id}/plan-runs")
    assert accepted.status_code == 202, accepted.text
    assert set(accepted.json()) == {"job_id", "notices"}
    assert accepted.json()["notices"] == [], "a project of 60 Included items or fewer gets no notice (D146)"
    job_id = str(accepted.json()["job_id"])
    deadline = time.monotonic() + PLAN_DEADLINE_S
    while True:
        job = client.get(f"/api/plan-jobs/{job_id}").json()
        if job["state"] in {"done", "failed"}:
            return job_id, dict(job)
        assert time.monotonic() < deadline, f"the job did not end: {job}"
        time.sleep(0.01)


def _planner_with(data_dir: Path, script: Script) -> TestClient:
    solver = ScriptedTourSolver(script)
    return _client({"DATA_DIR": str(data_dir)}, ExternalPorts(FakeClock(), FakeMountTable(), solver))


def test_a_plan_stores_every_stop_field_in_item_order_and_http_shows_the_contract(data_dir: Path) -> None:
    client = _planner_with(data_dir, None)  # the scripted tour visits the nodes in the order the snapshot lists them
    project_id, item_ids = _project_with_a_trail_between_two_places(client)

    job_id, job = _plan_job(client, project_id)

    assert set(job) == {
        *("state", "reason", "message", "plan_run_id", "elapsed_s", "memo_hit", "ignore_memo"),
        *("stage_ms", "legs_total", "legs_new", "legs_cached", "items_included", "incumbent", "stoppable"),
        *("second_pass_pairs", "retried", "notices"),  # 09-05: the poll shows them (brief section 5 field table)
    }
    assert (job["state"], job["reason"], job["message"], job["stoppable"]) == ("done", None, None, False)
    assert (job["retried"], job["second_pass_pairs"]) == (False, 0)
    stop = client.post(f"/api/plan-jobs/{job_id}/stop")
    assert (stop.status_code, stop.json()) == (200, job), "a Stop on a done job answers its final payload (D136)"
    assert set(job["stage_ms"]) == {"snapshot", "matrix", "reach_model", "solve", "guard_persist"}
    with sqlite3.connect(data_dir / "db" / "planner.sqlite") as connection:
        logged = connection.execute("SELECT project_id, terminal_state, plan_run_id FROM plan_job_log").fetchall()
    connection.close()
    assert logged == [(project_id, "done", job["plan_run_id"])], "the job writes its one plan_job_log row"
    shown = client.get(f"/api/plan-runs/{job['plan_run_id']}").json()
    assert set(shown) == {
        *("id", "project_id", "number", "status", "failure_reason", "stops", "totals", "report"),
        *("reproducible", "not_fully_optimised", "messages", "memo_hit", "objective", "objective_label"),
        "provider_header",
    }
    assert (shown["objective"], shown["objective_label"]) == ("distance", "minimise road distance")
    assert shown["provider_header"] == "Provider: offline estimate (straight line x 1.3) / profile: estimate"
    assert (shown["id"], shown["project_id"], shown["number"]) == (job["plan_run_id"], project_id, 1)
    assert (shown["status"], shown["failure_reason"]) == ("ready", None)
    assert (shown["reproducible"], shown["not_fully_optimised"], shown["memo_hit"]) == (True, None, False)
    assert shown["messages"] == ["Planned 2 items in 0.0 s"], "Briancon and the trail, on a clock that never moves"
    assert [(stop["name"], stop["type"]) for stop in shown["stops"]] == [
        ("Casa Marco", "poi"),
        ("Briancon", "poi"),
        (ASSIETTA, "track"),
        ("Casa Marco", "poi"),
    ]
    assert all(set(stop) == SHOWN_STOP_KEYS for stop in shown["stops"]), shown["stops"]
    assert shown["stops"][0]["leg_km"] is None

    database = SqliteDatabase(data_dir)
    with SqlAlchemyPlanningUnitOfWork(database, RecordingEventLog()) as uow:
        stored = uow.plan_runs.get(str(job["plan_run_id"]))
        items = uow.project_snapshots.read(project_id)
        row = uow.connection.execute(select(plan_runs)).mappings().one()
    assert stored is not None and items is not None
    assert [item.name for item in items.items] == ["Briancon", ASSIETTA, "Casa Marco"]
    saved = row["itinerary"]["stops"]
    assert [set(stop) for stop in saved] == [STORED_STOP_KEYS] * 4, "a stored stop key was renamed or lost"
    assert [stop["item_id"] for stop in saved] == [item_ids[name] for name in ("Casa Marco", "Briancon", ASSIETTA)] + [
        item_ids["Casa Marco"]
    ]
    expected: list[PlanStop] = []
    in_order = (items.start_item_id, item_ids["Briancon"], item_ids[ASSIETTA], items.end_item_id)
    for item_id, stop in zip(in_order, saved, strict=True):
        leg = None if stop["leg_km"] is None else (stop["leg_km"], stop["leg_s"])
        level = None if stop["leg_confidence"] is None else (stop["leg_confidence"], stop["leg_reason"])
        expected.append(PlanStop.driving(items.item(item_id), leg, items.offroad_speed, level).ending(expected))
    assert stored.stops == tuple(expected), "a column did not survive SQLite"
    track = items.item(item_ids[ASSIETTA])
    assert isinstance(track, TrackItem)
    assert (saved[2]["entry"], saved[2]["exit"]) == tuple(
        {"lat": point.latitude, "lon": point.longitude} for point in (track.entry, track.exit)
    )
    assert [[stop[column] for column in COLUMNS] for stop in shown["stops"]] == [
        [getattr(stop, column) for column in COLUMNS] for stop in stored.stops
    ], "HTTP shows the stored columns unrounded"
    assert [stop.leg_km for stop in stored.stops[1:]] == [stop["leg_km"] for stop in shown["stops"][1:]]
    assert (row["revision"], row["objective"]) == (
        client.get(f"/api/projects/{project_id}").json()["revision"],
        "distance",
    )
    assert row["provider_id"] == "mock:straight_line_x1.3"
    assert row["inputs"]["included_item_ids"] == [item_ids["Briancon"], item_ids[ASSIETTA]]

    before_columns = [{key: value for key, value in stop.items() if key not in COLUMNS} for stop in saved]
    # as a run stored before the columns were (01b, 05-06)
    with SqlAlchemyPlanningUnitOfWork(database, RecordingEventLog()) as uow:
        uow.connection.execute(plan_runs.update().values(itinerary={"stops": before_columns}))
        uow.commit()
    older = client.get(f"/api/plan-runs/{job['plan_run_id']}").json()
    assert [[stop[column] for column in COLUMNS] for stop in older["stops"]] == [[None] * len(COLUMNS)] * 4
    assert [{key: stop[key] for key in SHOWN_STOP_KEYS - set(COLUMNS)} for stop in older["stops"]] == [
        {key: stop[key] for key in SHOWN_STOP_KEYS - set(COLUMNS)} for stop in shown["stops"]
    ]


def test_a_failed_run_is_stored_without_stops_and_named_by_the_job(data_dir: Path) -> None:
    client = _planner_with(data_dir, TourNoRoute())
    project_id, _ = _project_with_a_trail_between_two_places(client)

    job = _plan(client, project_id)

    assert (job["state"], job["reason"]) == ("done", "no_valid_route_found")
    shown = client.get(f"/api/plan-runs/{job['plan_run_id']}").json()
    assert (shown["status"], shown["failure_reason"], shown["stops"]) == ("failed", "no_valid_route_found", [])
    assert client.get(f"/api/projects/{project_id}/plan-runs").json() == [
        {
            "id": shown["id"],
            "number": 1,
            "status": "failed",
            "stale": False,
            "reproducible": True,
            "not_fully_optimised": None,
        }
    ]


def test_a_job_that_raises_ends_failed_and_stores_nothing(data_dir: Path) -> None:
    client = _planner_with(data_dir, RuntimeError("the solver broke"))
    project_id, _ = _project_with_a_trail_between_two_places(client)

    job = _plan(client, project_id)

    assert (job["state"], job["reason"], job["plan_run_id"]) == ("failed", None, None)
    assert job["message"] == "The plan could not be calculated - nothing was changed"
    assert client.get(f"/api/projects/{project_id}/plan-runs").json() == []


def test_an_unknown_job_or_plan_run_is_not_found(data_dir: Path) -> None:
    client = _client({"DATA_DIR": str(data_dir)})

    for method, path in (
        ("GET", "/api/plan-jobs/nope"),
        ("GET", "/api/plan-runs/nope"),
        ("POST", "/api/plan-jobs/nope/stop"),
    ):
        answer = client.request(method, path)
        assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
        assert "nope" not in answer.json()["message"]
