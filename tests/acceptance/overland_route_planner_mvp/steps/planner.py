"""How the acceptance tests reach the planner: only through its driving ports (DISTILL D106, D107).

- `InProcessPlanner`: the real app from the production composition root, driven in-process (TestClient).
- `ServerPlanner`: the real app in a real `uvicorn --factory` server process, driven over real HTTP.
- `PlannerSession`: what one person's browser can do (optionally with basic-auth credentials). Every method is a
  driving-port call; no step definition talks to the database, the files or internal classes.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from overland_planner.bootstrap.app_factory import ExternalPorts, create_app

Auth = tuple[str, str] | None


class PlannerSession:
    """One person's view of the planner (HTTP API, DISTILL D107)."""

    def __init__(self, client: httpx.Client, auth: Auth = None) -> None:
        self._client = client
        self._auth = auth

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._auth is not None:
            kwargs.setdefault("auth", self._auth)
        return self._client.request(method, url, **kwargs)

    # --- platform -------------------------------------------------------------------------------------
    def home_page(self) -> httpx.Response:
        return self._request("GET", "/")

    def health(self) -> httpx.Response:
        return self._request("GET", "/healthz")

    def health_detail(self) -> httpx.Response:
        return self._request("GET", "/api/health")

    # --- catalog --------------------------------------------------------------------------------------
    def create_project(self, name: str) -> httpx.Response:
        return self._request("POST", "/api/projects", json={"name": name})

    def projects(self) -> httpx.Response:
        return self._request("GET", "/api/projects")

    def project(self, project_id: str) -> httpx.Response:
        return self._request("GET", f"/api/projects/{project_id}")

    def items(self, project_id: str) -> httpx.Response:
        return self._request("GET", f"/api/projects/{project_id}/items")

    def import_track_files(self, project_id: str, files: list[tuple[str, bytes]]) -> httpx.Response:
        multipart = [("files", (name, content, "application/gpx+xml")) for name, content in files]
        return self._request("POST", f"/api/projects/{project_id}/tracks", files=multipart)

    def add_poi(self, project_id: str, name: str, lat: float, lon: float) -> httpx.Response:
        return self._request("POST", f"/api/projects/{project_id}/pois", json={"name": name, "lat": lat, "lon": lon})

    def set_anchors(self, project_id: str, start_item_id: str | None, end_item_id: str | None) -> httpx.Response:
        """`None` keeps that anchor unset (slice 02: "set X as Start" while there is no End)."""
        return self._request(
            "PUT",
            f"/api/projects/{project_id}/anchors",
            json={"start_item_id": start_item_id, "end_item_id": end_item_id},
        )

    # --- catalog, slice 02 (brief §5: `?type=`, `PATCH /api/projects/{id}`, `DELETE .../items/{item_id}`) ----------
    def items_of_type(self, project_id: str, item_type: str) -> httpx.Response:
        return self._request("GET", f"/api/projects/{project_id}/items", params={"type": item_type})

    def update_project(self, project_id: str, **fields: Any) -> httpx.Response:
        return self._request("PATCH", f"/api/projects/{project_id}", json=fields)

    def remove_item(self, project_id: str, item_id: str) -> httpx.Response:
        return self._request("DELETE", f"/api/projects/{project_id}/items/{item_id}")

    # --- planning -------------------------------------------------------------------------------------
    def calculate(self, project_id: str, *, ignore_memo: bool = False) -> httpx.Response:
        """`ignore_memo` is "Re-optimise (ignore previous result)": `?ignore_memo=true`."""
        params = {"ignore_memo": "true"} if ignore_memo else None
        return self._request("POST", f"/api/projects/{project_id}/plan-runs", params=params)

    def plan_job(self, job_id: str) -> httpx.Response:
        return self._request("GET", f"/api/plan-jobs/{job_id}")

    def plan_runs(self, project_id: str) -> httpx.Response:
        return self._request("GET", f"/api/projects/{project_id}/plan-runs")

    def plan_run(self, plan_run_id: str) -> httpx.Response:
        return self._request("GET", f"/api/plan-runs/{plan_run_id}")

    def plan_run_geometry(self, plan_run_id: str) -> httpx.Response:
        return self._request("GET", f"/api/plan-runs/{plan_run_id}/geometry")

    def map_config(self) -> httpx.Response:
        return self._request("GET", "/api/config/map")

    def export_gpx(self, plan_run_id: str) -> httpx.Response:
        return self._request("GET", f"/api/plan-runs/{plan_run_id}/export.gpx")

    # --- slice 03 (brief §5: Stop, D136; diagnostics, DV-3 and kpi-contracts.yaml) -----------------------------
    def stop_plan_job(self, job_id: str) -> httpx.Response:
        """ "Stop and use best so far": always 200 with the current poll payload (D136); 404 for an unknown job."""
        return self._request("POST", f"/api/plan-jobs/{job_id}/stop")

    def diagnostics(self, project_id: str | None = None) -> httpx.Response:
        params = {"project_id": project_id} if project_id else None
        return self._request("GET", "/api/diagnostics", params=params)


class InProcessPlanner:
    """The production app built in-process; a restart builds a new app on the same data folder."""

    def __init__(self, environ: Mapping[str, str], external: ExternalPorts) -> None:
        self.environ = dict(environ)
        self.external = external
        self._client: Any = None

    def start(self) -> None:
        from fastapi.testclient import TestClient

        app = create_app(self.environ, external=self.external)
        self._client = TestClient(app, raise_server_exceptions=False)
        self._client.__enter__()

    def stop(self) -> None:
        if self._client is not None:
            self._client.__exit__(None, None, None)
            self._client = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def session(self, auth: Auth = None) -> PlannerSession:
        assert self._client is not None, "the planner is not running"
        return PlannerSession(self._client, auth)


@dataclass
class StartRecord:
    """What one start of the server process showed: its log lines and, if it ended, its exit code."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    exit_code: int | None = None
    answered: bool = False

    def json_lines(self) -> list[dict[str, Any]]:
        records = []
        for line in self.stdout:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def events(self, name: str) -> list[dict[str, Any]]:
        return [r for r in self.json_lines() if r.get("event") == name]

    def tail(self, lines: int = 25) -> str:
        out = "\n".join(self.stdout[-lines:])
        err = "\n".join(self.stderr[-lines:])
        return f"--- stdout (last {lines}) ---\n{out}\n--- stderr (last {lines}) ---\n{err}"


def descendants(root_pid: int) -> dict[int, str]:
    """Every process under `root_pid` with its command line, read from the process table."""
    table = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,ppid=,command="], capture_output=True, text=True, check=True)
    rows = [line.split(None, 2) for line in table.stdout.splitlines() if len(line.split(None, 2)) == 3]
    children: dict[int, list[tuple[int, str]]] = {}
    for pid, ppid, command in rows:
        children.setdefault(int(ppid), []).append((int(pid), command))
    found: dict[int, str] = {}
    pending = [root_pid]
    while pending:
        for pid, command in children.get(pending.pop(), []):
            pending.append(pid)
            found[pid] = command
    return found


def optimizer_processes(root_pid: int) -> list[int]:
    """The solve children under the planner process (multiprocessing spawn children), read from the process table."""
    return [pid for pid, command in descendants(root_pid).items() if "spawn_main" in command]


class LeftBehind:
    """The processes a planner process spawned, recorded before it is ended, so that the teardown can end those that
    outlived it (review F5). Only the teardown reaps: a scenario's own checks see what the product left running."""

    def __init__(self) -> None:
        self._recorded: dict[int, str] = {}

    def record(self, root_pid: int) -> None:
        self._recorded.update(descendants(root_pid))

    def reap(self) -> None:
        """SIGKILLs each recorded process still running the same command (a pid reused by another process is left)."""
        for pid, command in self._recorded.items():
            if _command_of(pid) == command:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(pid, signal.SIGKILL)
        self._recorded.clear()


def _command_of(pid: int) -> str | None:
    table = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, check=False)
    return table.stdout.strip() or None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ServerPlanner:
    """The production app served by a real uvicorn process (policy: Driving, WS / @wiring_e2e row)."""

    FACTORY = "overland_planner.bootstrap.app_factory:create_app"

    def __init__(self, environ: Mapping[str, str], workdir: Path, start_timeout_s: float = 45.0) -> None:
        self.environ = dict(environ)
        self.workdir = workdir
        self.start_timeout_s = start_timeout_s
        self.starts: list[StartRecord] = []
        self._process: subprocess.Popen[str] | None = None
        self._client: httpx.Client | None = None
        self._pumps: list[threading.Thread] = []
        self.base_url = ""
        self.left_behind = LeftBehind()  # what each ended process spawned; `reap_left_behind` ends the survivors

    def _child_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLANNER_", "ROUTING_", "MOCK_"))}
        env.pop("DATA_DIR", None)
        env.update(self.environ)
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def launch(self) -> StartRecord:
        """Start the process and wait until it answers its health check or ends. Never asserts."""
        port = _free_port()
        self.base_url = f"http://127.0.0.1:{port}"
        record = StartRecord()
        self.starts.append(record)
        self._process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "--factory", self.FACTORY, "--host", "127.0.0.1", "--port", str(port)],
            cwd=self.workdir,
            env=self._child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._pumps = []
        for stream, sink in ((self._process.stdout, record.stdout), (self._process.stderr, record.stderr)):
            pump = threading.Thread(target=_pump, args=(stream, sink), daemon=True)
            pump.start()
            self._pumps.append(pump)
        deadline = time.monotonic() + self.start_timeout_s
        while time.monotonic() < deadline:
            code = self._process.poll()
            if code is not None:
                self._join_pumps()  # every log line of the ended process is read before anyone asserts on it
                record.exit_code = code
                return record
            try:
                response = httpx.get(f"{self.base_url}/healthz", timeout=1.0)
                if response.status_code in (200, 503):
                    record.answered = True
                    self._client = httpx.Client(base_url=self.base_url, timeout=10.0)
                    return record
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        return record

    def start(self) -> None:
        """Start and require the planner to answer (precondition for a scenario)."""
        record = self.launch()
        assert record.answered, (
            f"The planner did not start (exit code {record.exit_code}) within {self.start_timeout_s:.0f} s.\n"
            f"{record.tail()}"
        )

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._process is not None and self._process.poll() is None:
            self.left_behind.record(self._process.pid)
            self._process.terminate()
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        if self._process is not None and self.starts:
            self._join_pumps()
            self.starts[-1].exit_code = self._process.returncode
        self._process = None

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def pid(self) -> int:
        assert self._process is not None, "the planner process is not running"
        return self._process.pid

    def kill_abruptly(self) -> None:
        """The planner is stopped abruptly: SIGKILL, no shutdown of its own (slice 03)."""
        assert self._process is not None, "the planner process is not running"
        self.left_behind.record(self._process.pid)
        self._process.kill()
        self._process.wait(timeout=10)

    def reap_left_behind(self) -> None:
        """Teardown only: ends what the ended planner processes spawned and left running (solve children)."""
        self.left_behind.reap()

    def session(self, auth: Auth = None) -> PlannerSession:
        assert self._client is not None, "the planner is not running"
        return PlannerSession(self._client, auth)

    def _join_pumps(self) -> None:
        for pump in getattr(self, "_pumps", []):
            pump.join(timeout=10)


class RemotePlanner:
    """A planner already running elsewhere, reached over real HTTP: `planner-perf` on the Pi through the loopback
    tunnel of `make perf-pi` (D96, slice 03-ops). Only `@requires_external @pi` scenarios use it.

    With PLANNER_PERF_USER and PLANNER_PERF_PASSWORD set (perf-pi reads them from the Pi's .env, 06-05) every request
    carries them as Basic auth: the household password guards the whole API."""

    USER_KEY = "PLANNER_PERF_USER"
    PASSWORD_KEY = "PLANNER_PERF_PASSWORD"  # noqa: S105 - the name of the variable, not a password

    def __init__(self, base_url: str, environ: Mapping[str, str] | None = None) -> None:
        self.base_url = base_url
        source = os.environ if environ is None else environ
        user, password = source.get(self.USER_KEY, ""), source.get(self.PASSWORD_KEY, "")
        self._auth = httpx.BasicAuth(user, password) if user and password else None
        self._client: httpx.Client | None = None

    def start(self) -> None:
        self._client = httpx.Client(base_url=self.base_url, timeout=60.0, auth=self._auth)
        health = self._client.get("/healthz")
        assert health.status_code == 200, f"the planner at {self.base_url} is not healthy: {health.status_code}"

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def session(self, auth: Auth = None) -> PlannerSession:
        assert self._client is not None, "the planner is not reachable"
        return PlannerSession(self._client, auth)


def _pump(stream: Any, sink: list[str]) -> None:
    if stream is None:
        return
    for line in stream:
        sink.append(line.rstrip("\n"))
