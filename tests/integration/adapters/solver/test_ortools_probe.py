"""OR-Tools solver probe in a short-lived child process (ADR-011 Amendment 1, ADR-015, brief §6 and §7).

Integration level: single examples verify wiring - the real spawned child for the healthy case, and the gold fault
catalogue (child crash, child hang, wrong order) through `create_app` over HTTP, with the faulty child given to the
real `OrToolsTourSolver` as `ExternalPorts(tour_solver=...)` (waiver W2). The verdict invariants live in
tests/unit/adapters/solver/test_probe_verdict.py.

The faulty child entry points below are module-level so the spawn context can import them in the child.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from multiprocessing.connection import Connection

import pytest
from fastapi.testclient import TestClient

from overland_planner.adapters.solver.ortools_tour_solver import OrToolsTourSolver
from overland_planner.adapters.solver.probe_instance import (
    FORBIDDEN_ARC,
    KNOWN_OPTIMAL_ORDER,
    KNOWN_OPTIMUM,
    NODE_COUNT,
    arc_cost,
)
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from tests.common.fakes import FakeClock

pytestmark = pytest.mark.solver_child

OPTIMIZER_UNAVAILABLE = ProbeResult(outcome="degraded-unhealthy", reason="optimizer_unavailable")


def _crashing_child(_answer: Connection) -> None:
    os._exit(3)


def _hanging_child(_answer: Connection) -> None:
    time.sleep(60)


def _wrong_order_child(answer: Connection) -> None:
    wrong = tuple(reversed(KNOWN_OPTIMAL_ORDER))
    answer.send(((wrong, KNOWN_OPTIMUM), (wrong, KNOWN_OPTIMUM)))
    answer.close()


def _brute_force_optimum() -> tuple[tuple[int, ...], int]:
    """Independent oracle: enumerate every tour from the depot (node 0) that avoids the forbidden arc."""
    tours = []
    for order in itertools.permutations(range(1, NODE_COUNT)):
        path = (0, *order, 0)
        arcs = list(itertools.pairwise(path))
        if FORBIDDEN_ARC not in arcs:
            tours.append((sum(arc_cost(a, b) for a, b in arcs), order))
    (best_cost, best_order), (runner_up_cost, _) = sorted(tours)[:2]
    assert best_cost < runner_up_cost, "the probe instance must have a unique optimum"
    return best_order, best_cost


def test_probe_solves_known_instance_twice_identically() -> None:
    assert _brute_force_optimum() == (KNOWN_OPTIMAL_ORDER, KNOWN_OPTIMUM)

    assert OrToolsTourSolver().probe() == ProbeResult(outcome="ok")


def _degraded_client(child_main: object, timeout_s: float = 10.0) -> TestClient:
    solver = OrToolsTourSolver(child_main=child_main, timeout_s=timeout_s)  # type: ignore[arg-type]
    return TestClient(create_app({}, external=ExternalPorts(clock=FakeClock(), tour_solver=solver)))


def _assert_optimizer_unavailable(client: TestClient) -> None:
    health = client.get("/healthz")
    detail = client.get("/api/health")

    assert (health.status_code, health.json()) == (503, {"status": "unhealthy", "reason": "optimizer_unavailable"})
    assert detail.status_code == 200
    body = detail.json()
    assert body["components"]["tour_solver"] == {"outcome": "degraded-unhealthy", "reason": "optimizer_unavailable"}
    assert body["components"]["clock"] == {"outcome": "ok", "reason": None}
    assert body["banners"] == ["optimizer_unavailable"]


def test_child_crash_degrades_with_optimizer_unavailable(capsys: pytest.CaptureFixture[str]) -> None:
    client = _degraded_client(_crashing_child)

    _assert_optimizer_unavailable(client)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    degraded = [line for line in lines if line["event"] == "health.startup.degraded"]
    assert [(line["component"], line["reason"]) for line in degraded] == [("tour_solver", "optimizer_unavailable")]
    assert [line["event"] for line in lines][-1] == "app.started"


def test_child_timeout_degrades_with_optimizer_unavailable() -> None:
    started = time.monotonic()
    client = _degraded_client(_hanging_child, timeout_s=1.0)
    elapsed = time.monotonic() - started

    _assert_optimizer_unavailable(client)
    assert elapsed < 5.0, f"a hanging child must be killed at its timeout, start-up took {elapsed:.1f}s"


def test_wrong_order_degrades_with_optimizer_unavailable() -> None:
    _assert_optimizer_unavailable(_degraded_client(_wrong_order_child))
