"""Composition-root wiring (driving port: `create_app`, and the production `uvicorn --factory` command).

Integration level: single examples verify wiring (settings source, event log, clock), not input invariants.
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from overland_planner.adapters.files.local_file_store import LocalFileStore
from overland_planner.adapters.persistence.database import database_file
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.common.fakes import FakeClock
from tests.common.solver_fakes import HoldingTourSolver, UnavailableTourSolver
from tests.common.workspace import workspace_data_dir
from tests.unit.application.planning.scripted_tour_solver import ScriptedTourSolver

REPO_ROOT = Path(__file__).resolve().parents[3]
FACTORY = "overland_planner.bootstrap.app_factory:create_app"


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """A fresh DATA_DIR under the workspace, never the OS temp folder (D182), removed after the test."""
    with workspace_data_dir("integration") as folder:
        yield folder


def _json_lines(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _started(text: str) -> list[dict[str, Any]]:
    return [record for record in _json_lines(text) if record.get("event") == "app.started"]


def test_create_app_reads_os_environ_when_given_no_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], data_dir: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("PLANNER_GIT_SHA", "0123456789ab")
    monkeypatch.setenv("ROUTING_PROVIDER", "mock")

    create_app()

    (started,) = _started(capsys.readouterr().out)
    assert started["app_version"] == "0123456789ab"


def test_create_app_given_a_mapping_reads_only_that_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], data_dir: Path
) -> None:
    monkeypatch.setenv("PLANNER_GIT_SHA", "from-process-env")
    monkeypatch.setenv("ROUTING_PROVIDER", "osrm")  # would be refused if the process environment were read

    create_app({"PLANNER_GIT_SHA": "from-mapping", "DATA_DIR": str(data_dir)})

    (started,) = _started(capsys.readouterr().out)
    assert started["app_version"] == "from-mapping"
    assert started["routing_provider"] == "mock"


def test_an_invalid_setting_refuses_start_up_naming_the_setting(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(StartupRefusedError) as refused:
        create_app({"ROUTING_PROVIDER": "osrm"})

    assert (refused.value.code, refused.value.component) == (1, "settings")
    (line,) = _json_lines(capsys.readouterr().out)
    assert (line["event"], line["component"]) == ("health.startup.refused", "settings")
    assert "ROUTING_PROVIDER" in line["reason"]


def test_every_event_is_one_json_line_with_utc_timestamp(capsys: pytest.CaptureFixture[str], data_dir: Path) -> None:
    clock = FakeClock(datetime(2026, 11, 2, 19, 30, 15, 250_000, tzinfo=UTC))

    create_app({"PLANNER_GIT_SHA": "abc", "DATA_DIR": str(data_dir)}, external=ExternalPorts(clock=clock))

    records = _json_lines(capsys.readouterr().out)  # every stdout line must parse as one JSON object
    assert records, "no event was logged"
    for record in records:
        assert isinstance(record["event"], str)
        assert datetime.fromisoformat(record["ts"]) == clock.now()
        assert record["ts"].endswith("Z") or record["ts"].endswith("+00:00")


def _start_server_once(environ: dict[str, str]) -> str:
    """Run the production command until the app has started, stop it, and return its whole stdout."""
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory", FACTORY, "--host", "127.0.0.1", "--port", "0"],
        cwd=REPO_ROOT,
        env=environ,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stderr is not None
    deadline = time.monotonic() + 30
    for line in process.stderr:  # uvicorn reports readiness on stderr
        if "Application startup complete" in line or time.monotonic() > deadline:
            break
    process.terminate()
    stdout, stderr = process.communicate(timeout=15)
    assert process.returncode in (0, -15), stderr
    return stdout


def test_each_start_logs_one_app_started_line(data_dir: Path) -> None:
    environ = {k: v for k, v in os.environ.items() if not k.startswith(("PLANNER_", "ROUTING_"))}
    environ.update({"PYTHONUNBUFFERED": "1", "DATA_DIR": str(data_dir), "PLANNER_GIT_SHA": "0123456789ab"})

    for start in (1, 2):
        started = _started(_start_server_once(environ))
        assert len(started) == 1, f"start {start}: expected one app.started line, found {len(started)}"
        assert started[0]["app_version"] == "0123456789ab"
        assert started[0]["routing_provider"] == "mock"
        assert started[0]["python_version"] == platform.python_version()
        assert started[0]["alembic_revision"] == "0008"


def _planner(data_dir: Path) -> TestClient:
    return TestClient(
        create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=UnavailableTourSolver()))
    )


def _project_with_a_place(client: TestClient) -> tuple[str, str]:
    project_id = client.post("/api/projects", json={"name": "Alpi"}).json()["id"]
    place = client.post(f"/api/projects/{project_id}/pois", json={"name": "Casa", "lat": 45.07, "lon": 7.68})
    return project_id, place.json()["id"]


def _sql(data_dir: Path, statement: str, *parameters: str | None) -> None:
    connection = sqlite3.connect(database_file(data_dir))
    with connection:
        connection.execute(statement, parameters)
    connection.close()


def _stored_settings(data_dir: Path, project_id: str) -> Any:
    connection = sqlite3.connect(database_file(data_dir))
    (settings,) = connection.execute("SELECT settings FROM projects WHERE id = ?", (project_id,)).fetchone()
    connection.close()
    return json.loads(settings)


def test_a_project_stored_before_its_settings_drives_at_15_kmh_and_a_set_speed_is_kept(data_dir: Path) -> None:
    client = _planner(data_dir)
    project_id, _ = _project_with_a_place(client)
    _sql(data_dir, "UPDATE projects SET settings = '{}' WHERE id = ?", project_id)  # as written before slice 02
    assert client.get(f"/api/projects/{project_id}").json()["offroad_speed_kmh"] == 15

    changed = client.patch(f"/api/projects/{project_id}", json={"offroad_speed_kmh": 22.5})

    assert (changed.status_code, changed.json()["offroad_speed_kmh"]) == (200, 22.5)
    assert _stored_settings(data_dir, project_id) == {"offroad_speed_kmh": 22.5}
    reopened = _planner(data_dir).get(f"/api/projects/{project_id}")
    assert reopened.json()["offroad_speed_kmh"] == 22.5, "read back by a new planner process from the database"


def test_a_stored_speed_that_is_not_drivable_reads_15_kmh_with_a_warning_and_a_patch_repairs_it(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _planner(data_dir)
    project_id, _ = _project_with_a_place(client)
    _sql(data_dir, "UPDATE projects SET settings = '{\"offroad_speed_kmh\": 0}' WHERE id = ?", project_id)  # by hand
    capsys.readouterr()

    listed = client.get("/api/projects")

    assert listed.status_code == 200
    assert [project["offroad_speed_kmh"] for project in listed.json() if project["id"] == project_id] == [15]
    (invalid,) = [r for r in _json_lines(capsys.readouterr().out) if r.get("event") == "catalog.settings.invalid"]
    assert (invalid["level"], invalid["project_id"], invalid["field"]) == ("warning", project_id, "offroad_speed_kmh")
    assert client.get(f"/api/projects/{project_id}").json()["offroad_speed_kmh"] == 15

    repaired = client.patch(f"/api/projects/{project_id}", json={"offroad_speed_kmh": 20})

    assert (repaired.status_code, repaired.json()["offroad_speed_kmh"]) == (200, 20)
    assert _stored_settings(data_dir, project_id) == {"offroad_speed_kmh": 20}


@pytest.mark.parametrize("stored", ['"20"', "true", "[20]"], ids=["string", "bool", "list"])
def test_a_stored_speed_that_is_not_a_json_number_reads_15_kmh_with_a_warning(
    data_dir: Path, capsys: pytest.CaptureFixture[str], stored: str
) -> None:
    client = _planner(data_dir)
    project_id, _ = _project_with_a_place(client)
    settings = f'{{"offroad_speed_kmh": {stored}}}'
    _sql(data_dir, "UPDATE projects SET settings = ? WHERE id = ?", settings, project_id)  # by hand
    capsys.readouterr()

    listed = client.get("/api/projects")

    assert listed.status_code == 200
    assert [project["offroad_speed_kmh"] for project in listed.json() if project["id"] == project_id] == [15]
    (invalid,) = [r for r in _json_lines(capsys.readouterr().out) if r.get("event") == "catalog.settings.invalid"]
    assert (invalid["level"], invalid["project_id"], invalid["field"]) == ("warning", project_id, "offroad_speed_kmh")
    assert client.get(f"/api/projects/{project_id}").json()["offroad_speed_kmh"] == 15


def test_the_plan_run_list_is_empty_until_a_run_exists_then_ordered_by_number(data_dir: Path) -> None:
    client = _planner(data_dir)
    project_id, _ = _project_with_a_place(client)
    assert client.get(f"/api/projects/{project_id}/plan-runs").json() == []

    for run_id, number, status in (("r10", "10", "failed"), ("r2", "2", "ready")):
        _sql(
            data_dir,
            "INSERT INTO plan_runs (id, project_id, number, status, created_at, revision, provider_id, objective, "
            "inputs) VALUES (?, ?, ?, ?, '2026-11-04 08:00:00', 1, 'mock', 'distance', '{}')",
            run_id,
            project_id,
            number,
            status,
        )

    answer = client.get(f"/api/projects/{project_id}/plan-runs")
    assert (answer.status_code, answer.json()) == (
        200,
        [
            {
                "id": "r2",
                "number": 2,
                "status": "ready",
                "stale": True,
                "reproducible": True,
                "not_fully_optimised": None,
            },
            {
                "id": "r10",
                "number": 10,
                "status": "failed",
                "stale": True,
                "reproducible": True,
                "not_fully_optimised": None,
            },
        ],
    )


def _stored_run(data_dir: Path, project_id: str, status: str, itinerary: str | None = None) -> str:
    run_id = uuid.uuid4().hex
    _sql(
        data_dir,
        "INSERT INTO plan_runs (id, project_id, number, status, created_at, revision, provider_id, objective, "
        "inputs, itinerary) VALUES (?, ?, '1', ?, '2026-11-04 08:00:00', 1, 'mock', 'distance', '{}', ?)",
        run_id,
        project_id,
        status,
        itinerary,
    )
    return run_id


def test_exporting_a_failed_run_answers_422_with_its_message(data_dir: Path) -> None:
    client = _planner(data_dir)
    project_id, _ = _project_with_a_place(client)
    run_id = _stored_run(data_dir, project_id, "failed")

    answer = client.get(f"/api/plan-runs/{run_id}/export.gpx")

    assert (answer.status_code, answer.json()) == (422, {"code": "validation_error", "message": "This plan run failed"})


def test_exporting_a_run_whose_track_file_changed_answers_422_with_its_message(data_dir: Path) -> None:
    client = _planner(data_dir)
    project_id, _ = _project_with_a_place(client)
    itinerary = {
        "stops": [
            {
                "item_id": "assietta",
                "name": "Strada dell'Assietta",
                "kind": "track",
                "leg_km": None,
                "location": None,
                "entry": {"lat": 45.05, "lon": 7.04},
                "exit": {"lat": 44.96, "lon": 6.88},
                "direction_version": 1,
                "point_count": 2,
                "canonical_sha256": "the hash of what the run recorded",
            }
        ]
    }
    LocalFileStore(data_dir).keep_canonical_points("assietta", 1, b"other bytes")
    run_id = _stored_run(data_dir, project_id, "ready", json.dumps(itinerary))

    answer = client.get(f"/api/plan-runs/{run_id}/export.gpx")

    assert (answer.status_code, answer.json()) == (
        422,
        {"code": "validation_error", "message": "Track data for this run is inconsistent - recalculate"},
    )


def _refusal(client: TestClient, calculate: str) -> tuple[int, dict[str, str]]:
    answer = client.post(calculate)
    return answer.status_code, answer.json()


def test_calculate_answers_the_missing_anchor_read_from_the_database(data_dir: Path) -> None:
    client = _planner(data_dir)
    project_id, place_id = _project_with_a_place(client)
    calculate = f"/api/projects/{project_id}/plan-runs"
    start_message = {"code": "missing_anchor", "message": "Set the Start before calculating"}
    end_message = {"code": "missing_anchor", "message": "Set the End before calculating"}

    assert _refusal(client, calculate) == (422, start_message)

    _sql(data_dir, "UPDATE projects SET start_item_id = ?", place_id)
    assert _refusal(client, calculate) == (422, end_message)

    _sql(data_dir, "UPDATE projects SET start_item_id = NULL, end_item_id = ?", place_id)
    assert _refusal(client, calculate) == (422, start_message)


UNKNOWN = "0" * 32


@pytest.mark.parametrize(
    ("method", "path", "message"),
    [
        ("GET", f"/api/projects/{UNKNOWN}/plan-runs", "Project not found"),
        ("POST", f"/api/projects/{UNKNOWN}/plan-runs", "Project not found"),
        ("GET", f"/api/plan-runs/{UNKNOWN}", "Plan run not found"),
        ("GET", f"/api/plan-jobs/{UNKNOWN}", "Plan job not found"),
    ],
)
def test_an_unknown_id_is_not_found_with_a_fixed_message(data_dir: Path, method: str, path: str, message: str) -> None:
    answer = _planner(data_dir).request(method, path)
    assert (answer.status_code, answer.json()) == (404, {"code": "not_found", "message": message})


def test_an_unknown_item_of_a_known_project_is_not_found_with_a_fixed_message(data_dir: Path) -> None:
    client = _planner(data_dir)
    project_id, _ = _project_with_a_place(client)
    answer = client.delete(f"/api/projects/{project_id}/items/{UNKNOWN}")
    assert (answer.status_code, answer.json()) == (404, {"code": "not_found", "message": "Item not found"})


def test_a_second_calculate_is_refused_until_the_job_has_ended_even_when_it_failed(data_dir: Path) -> None:
    solver = HoldingTourSolver(ScriptedTourSolver())
    client = TestClient(create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=solver)))
    project_id, place_id = _project_with_a_place(client)
    client.put(f"/api/projects/{project_id}/anchors", json={"start_item_id": place_id, "end_item_id": place_id})
    calculate = f"/api/projects/{project_id}/plan-runs"
    first = client.post(calculate)
    assert first.status_code == 202
    assert solver.wait_until_asked(30)

    assert _refusal(client, calculate) == (
        409,
        {"code": "job_active", "message": "A plan is already being calculated for this project"},
    )

    solver.abandon()
    job_id = first.json()["job_id"]
    deadline = time.monotonic() + 30
    while (job := client.get(f"/api/plan-jobs/{job_id}").json())["state"] != "failed":
        assert time.monotonic() < deadline, f"the job did not fail: {job}"
    assert job["plan_run_id"] is None
    assert client.post(calculate).status_code == 202


def _ended_job(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while (job := client.get(f"/api/plan-jobs/{job_id}").json())["state"] not in {"done", "failed"}:
        assert time.monotonic() < deadline, f"the job did not end: {job}"
    return dict(job)


def test_calculate_takes_ignore_memo_as_a_boolean_and_its_poll_shows_it(data_dir: Path) -> None:
    client = TestClient(
        create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=ScriptedTourSolver()))
    )
    project_id, place_id = _project_with_a_place(client)
    client.put(f"/api/projects/{project_id}/anchors", json={"start_item_id": place_id, "end_item_id": place_id})
    calculate = f"/api/projects/{project_id}/plan-runs"

    refused = client.post(calculate, params={"ignore_memo": "perhaps"})

    assert (refused.status_code, refused.json().get("code")) == (422, "validation_error")
    assert client.get(f"/api/projects/{project_id}/plan-runs").json() == [], "a refused Calculate stored a run"
    for sent, shown in ((None, False), ("true", True)):
        params = {} if sent is None else {"ignore_memo": sent}
        accepted = client.post(calculate, params=params)  # 202, not 409: the refused press started no job
        assert accepted.status_code == 202, accepted.text
        job = _ended_job(client, accepted.json()["job_id"])
        assert (job["state"], job["ignore_memo"], job["memo_hit"]) == ("done", shown, False)


def test_identical_inputs_after_a_restart_reuse_the_stored_order_through_sqlite(data_dir: Path) -> None:
    """The fingerprint and memo_hit round trip through SQLite (05-10): one solve, then a memo hit after a restart."""
    first_solver, second_solver = ScriptedTourSolver(), ScriptedTourSolver()
    client = TestClient(create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=first_solver)))
    project_id, place_id = _project_with_a_place(client)
    client.put(f"/api/projects/{project_id}/anchors", json={"start_item_id": place_id, "end_item_id": place_id})
    calculate = f"/api/projects/{project_id}/plan-runs"
    solved = _ended_job(client, client.post(calculate).json()["job_id"])
    restarted = TestClient(create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=second_solver)))

    reused = _ended_job(restarted, restarted.post(calculate).json()["job_id"])

    assert (solved["memo_hit"], reused["memo_hit"]) == (False, True)
    assert (len(first_solver.models), len(second_solver.models)) == (1, 0)
    connection = sqlite3.connect(database_file(data_dir))
    rows = connection.execute("SELECT number, status, fingerprint, memo_hit FROM plan_runs ORDER BY number").fetchall()
    connection.close()
    assert [(number, status, memo_hit) for number, status, _, memo_hit in rows] == [(1, "ready", 0), (2, "ready", 1)]
    assert rows[0][2] == rows[1][2] and str(rows[0][2]).startswith("fp2:"), f"the fingerprints are {rows}"
    first, second = (restarted.get(f"/api/plan-runs/{job['plan_run_id']}").json() for job in (solved, reused))
    assert (first["stops"], first["totals"]) == (second["stops"], second["totals"])


def test_another_solver_wired_after_a_restart_gives_another_fingerprint_and_solves_again(data_dir: Path) -> None:
    """The memo is keyed by the identity of the solver the composition root wired, not a constant of OR-Tools."""
    first_solver, second_solver = ScriptedTourSolver(identity="scripted:a"), ScriptedTourSolver(identity="scripted:b")
    client = TestClient(create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=first_solver)))
    project_id, place_id = _project_with_a_place(client)
    client.put(f"/api/projects/{project_id}/anchors", json={"start_item_id": place_id, "end_item_id": place_id})
    calculate = f"/api/projects/{project_id}/plan-runs"
    solved = _ended_job(client, client.post(calculate).json()["job_id"])
    restarted = TestClient(create_app({"DATA_DIR": str(data_dir)}, external=ExternalPorts(tour_solver=second_solver)))

    again = _ended_job(restarted, restarted.post(calculate).json()["job_id"])

    assert (solved["memo_hit"], again["memo_hit"]) == (False, False)
    assert (len(first_solver.models), len(second_solver.models)) == (1, 1)
    connection = sqlite3.connect(database_file(data_dir))
    fingerprints = [row[0] for row in connection.execute("SELECT fingerprint FROM plan_runs ORDER BY number")]
    connection.close()
    assert len(set(fingerprints)) == 2, f"the fingerprints are {fingerprints}"
