"""Scenario state shared by the step definitions, and the port-exposed universe (Mandate 8).

Universe names are what Marco can observe through the driving ports (DISTILL D115), never internal fields:
- `projects.names`  -> the project list on the home page (GET /api/projects)
- `project.items`   -> the item list of the open project: (type, name, included, anchor badge)
- `project.plan_runs` -> the plan runs of the open project: (number, status)
(The earlier `saved_data.database` file fingerprint was removed: review H-07, DISTILL D185.)

Error responses follow the HTTP contract (brief §5, D130): `{"code", "message"}` with an enumerated code per status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from overland_planner.application.ports.tour_solver import TourSolver
from overland_planner.bootstrap.app_factory import ExternalPorts
from tests.acceptance.overland_route_planner_mvp.steps.planner import (
    Auth,
    InProcessPlanner,
    PlannerSession,
    RemotePlanner,
    ServerPlanner,
    StartRecord,
)
from tests.common.fakes import FakeClock, FakeMountTable
from tests.common.solver_fakes import HoldingTourSolver, ScriptedTourSolver

CATALOG_UNIVERSE = {"projects.names", "project.items"}
PLANNING_UNIVERSE = CATALOG_UNIVERSE | {"project.plan_runs"}

ERROR_CODES = {  # brief §5 "HTTP contract" (D130)
    401: {"unauthorized"},
    404: {"not_found"},
    409: {"job_active"},
    413: {"upload_too_large"},
    422: {"validation_error", "missing_anchor"},
    503: {"routing_engine_not_ready", "optimizer_unavailable"},
}
BADGE_TO_ANCHOR = {"S/E": "start_end", "Start": "start", "End": "end"}
REFUSALS = {  # what Marco reads -> the status and code of that refusal (brief §5, §8; D183)
    "Optimizer unavailable - nothing was changed": (503, "optimizer_unavailable"),
    "A plan is already being calculated for this project": (409, "job_active"),
    # slice 02 (D201 for the End)
    "Set the Start before calculating": (422, "missing_anchor"),
    "Set the End before calculating": (422, "missing_anchor"),
    "Only places (POIs) can be the Start or End": (422, "validation_error"),
    "Off-road speed must be more than 0 km/h": (422, "validation_error"),
}


@dataclass
class PlannerWorld:
    tmp_path: Path
    data_dir: Path
    environ: dict[str, str]
    clock: FakeClock
    mount_table: FakeMountTable
    tour_solver: TourSolver | None = None  # None = the real optimizer; doubles only under waivers W1/W2
    planner: InProcessPlanner | ServerPlanner | RemotePlanner | None = None
    marco_auth: Auth = None
    project_id: str | None = None
    project_name: str | None = None
    last_track_name: str | None = None
    response: httpx.Response | None = None
    seen_messages: list[str] = field(default_factory=list)
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    last_start: StartRecord | None = None
    giulia_responses: dict[str, httpx.Response] = field(default_factory=dict)
    anchors_requested: tuple[str, str] | None = None
    scratch: dict[str, Any] = field(default_factory=dict)

    # --- the planner under test ------------------------------------------------------------------------
    def ensure_planner(self) -> None:
        if self.planner is None:
            self.planner = InProcessPlanner(
                self.environ,
                ExternalPorts(clock=self.clock, mount_table=self.mount_table, tour_solver=self.tour_solver),
            )
            self.planner.start()

    def marco(self) -> PlannerSession:
        assert self.planner is not None, "the planner is not running"
        return self.planner.session(self.marco_auth)

    def shutdown(self) -> None:
        if isinstance(self.tour_solver, HoldingTourSolver | ScriptedTourSolver):
            self.tour_solver.abandon()
        if self.planner is not None:
            self.planner.stop()

    # --- what Marco observes ---------------------------------------------------------------------------
    def note(self, response: httpx.Response) -> httpx.Response:
        self.response = response
        if response.status_code >= 400:
            message = _message_of(response)
            if message:
                self.seen_messages.append(message)
        return response

    def catalog_view(self) -> dict[str, Any]:
        marco = self.marco()
        listed = marco.projects()
        assert listed.status_code == 200, f"the project list did not open: {listed.status_code} {listed.text[:300]}"
        view: dict[str, Any] = {"projects.names": tuple(sorted(p["name"] for p in listed.json()))}
        if self.project_id is not None:
            items = marco.items(self.project_id)
            assert items.status_code == 200, f"the item list did not open: {items.status_code} {items.text[:300]}"
            view["project.items"] = tuple(sorted(item_row(i) for i in items.json()))
        else:
            view["project.items"] = ()
        return view

    def planning_view(self) -> dict[str, Any]:
        assert self.project_id is not None, "no project is open"
        runs = self.marco().plan_runs(self.project_id)
        assert runs.status_code == 200, f"the plan runs did not open: {runs.status_code} {runs.text[:300]}"
        rows = tuple(sorted((run["number"], run["status"]) for run in runs.json()))
        return {**self.catalog_view(), "project.plan_runs": rows}

    def items(self) -> list[dict[str, Any]]:
        assert self.project_id is not None, "no project is open"
        response = self.marco().items(self.project_id)
        assert response.status_code == 200, f"the item list did not open: {response.status_code}"
        return list(response.json())

    def item_named(self, name: str) -> dict[str, Any]:
        matches = [i for i in self.items() if i["name"] == name]
        assert len(matches) == 1, f"expected exactly one item named {name!r}, found {len(matches)}"
        return matches[0]



def item_row(item: dict[str, Any]) -> tuple[str, str, bool, str | None]:
    return (item["type"], item["name"], bool(item["included"]), item.get("anchor"))


def assert_error_envelope(response: httpx.Response) -> None:
    """Every non-2xx answer under /api is {"code", "message"} with the code enumerated for its status (D130)."""
    body = response.json()
    assert set(body) >= {"code", "message"}, f"not the error envelope: {body}"
    allowed = ERROR_CODES.get(response.status_code, set())
    assert body["code"] in allowed, f"status {response.status_code} with code {body['code']!r}, expected one of {allowed}"


def _message_of(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        message = body.get("message") or body.get("reason")
        return str(message) if message else None
    return None
