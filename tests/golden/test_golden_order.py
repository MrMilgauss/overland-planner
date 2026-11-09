"""The golden-order check: I1 and I2 still plan to their blessed order (slice 03-ops; D96, D160, D175; CI job 3).

    uv run pytest -q -m golden_order

Each reference project is planned through the HTTP API in a fresh in-process planner with the real OR-Tools child at
the default budget (10,000; I2 with its road map as MOCK_PLAN), Calculate with ignore_memo
(`tests.perf.golden_instances`, the bless path). The check passes when the stop-name order hashes to the committed
sha and otherwise fails naming the instance and both hashes. A re-bless is the only way to change the golden order.

Job summary (only when GITHUB_STEP_SUMMARY is set): each instance's sha and its solve seconds, the latter advisory: a
slower runner never fails the check, a different sha always does. Until 06-03 the solve seconds are the job's
`elapsed_s`, from 06-03 its `stage_ms.solve`; an in-process planner runs on a fake clock (its limits never cut a
search short on a slow runner), so there the wall clock from Calculate to done is shown instead.

Remote mode (06-05, D175: the same check on the production arch and image): with PLANNER_PERF_URL set the check plans
against that planner instead, seeding a project named '__perf golden <instance> <timestamp>' (outside K1/K7), and
GOLDEN_INSTANCE=i1 or i2 names the instance whose road map that planner was started with.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.acceptance.overland_route_planner_mvp.steps.planner import RemotePlanner
from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld
from tests.common.fakes import FakeClock, FakeMountTable
from tests.perf.golden_instances import (
    COMMITTED,
    I1_DENSE,
    I2_SPARSE,
    KINDS,
    SOLVER_BUDGET,
    PlannedOrder,
    TripData,
    committed_trip,
    order_sha256,
    plan_in_fresh_planner,
    plan_on,
)

PERF_URL_KEY = "PLANNER_PERF_URL"
INSTANCE_KEY = "GOLDEN_INSTANCE"
INSTANCES = {"i1": I1_DENSE, "i2": I2_SPARSE}
SUMMARY_KEY = "GITHUB_STEP_SUMMARY"


@dataclass(frozen=True)
class GoldenResult:
    kind: str
    expected_sha: str
    actual_sha: str
    solve_s: float
    solve_source: str

    @property
    def matches(self) -> bool:
        return self.actual_sha == self.expected_sha


def selected_kinds(environ: Mapping[str, str]) -> tuple[str, ...]:
    chosen = environ.get(INSTANCE_KEY, "")
    if not chosen:
        assert not environ.get(PERF_URL_KEY), (
            f"remote mode plans one instance: set {INSTANCE_KEY}=i1 or i2, the road map that planner was started with"
        )
        return KINDS
    assert chosen in INSTANCES, f"{INSTANCE_KEY}={chosen!r}: expected one of {', '.join(INSTANCES)}"
    return (INSTANCES[chosen],)


def plan_remotely(url: str, kind: str, trip: TripData) -> PlannedOrder:
    scratch = Path(tempfile.gettempdir())  # a remote planner keeps its data on its own host
    world = PlannerWorld(scratch, scratch, {}, FakeClock(), FakeMountTable())
    planner = RemotePlanner(url)
    world.planner = planner
    planner.start()
    try:
        return plan_on(world, f"__perf golden {kind} {time.strftime('%Y%m%d-%H%M%S')}", trip)
    finally:
        world.shutdown()


def solve_seconds(planned: PlannedOrder) -> tuple[float, str]:
    """The planner's own figure when its clock is real (remote mode), else the wall clock of this run."""
    solve_ms = (planned.job.get("stage_ms") or {}).get("solve")
    if isinstance(solve_ms, int | float) and solve_ms > 0:
        return solve_ms / 1000, "stage_ms.solve"
    elapsed = planned.job.get("elapsed_s")
    if isinstance(elapsed, int | float) and elapsed > 0:
        return float(elapsed), "elapsed_s"
    return planned.wall_s, "wall clock, Calculate to done"


def plan_golden(kind: str, environ: Mapping[str, str]) -> GoldenResult:
    fixture = COMMITTED / f"{kind}.json"
    trip = committed_trip(fixture)
    assert trip.expected_order_sha256, f"{kind} has no blessed golden order"
    assert trip.solver_budget == SOLVER_BUDGET, f"{kind} was blessed at budget {trip.solver_budget}"
    url = environ.get(PERF_URL_KEY)
    if url:
        planned = plan_remotely(url, kind, trip)
    else:
        road_map = json.loads(fixture.read_text(encoding="utf-8"))["road_map"]
        planned = plan_in_fresh_planner(trip, COMMITTED / road_map if road_map else None)
    seconds, source = solve_seconds(planned)
    return GoldenResult(kind, trip.expected_order_sha256, order_sha256(planned.names), seconds, source)


def write_summary(results: list[GoldenResult], environ: Mapping[str, str]) -> None:
    summary = environ.get(SUMMARY_KEY)
    if not summary:
        return
    rows = "".join(
        f"| {r.kind} | `{r.actual_sha}` | {'same' if r.matches else f'DIFFERENT (golden `{r.expected_sha}`)'} | "
        f"{r.solve_s:.1f} ({r.solve_source}) |\n"
        for r in results
    )
    with Path(summary).open("a", encoding="utf-8") as out:
        out.write(
            "### Golden order\n"
            "A different sha fails the check; the solve seconds are advisory (a slower runner never fails it).\n\n"
            "| instance | order sha256 | against the golden | solve s (advisory) |\n"
            "|---|---|---|---|\n" + rows
        )


def check_golden_orders(environ: Mapping[str, str]) -> list[GoldenResult]:
    results = [plan_golden(kind, environ) for kind in selected_kinds(environ)]
    write_summary(results, environ)
    differing = [
        f"{r.kind}: the planner returns order sha256 {r.actual_sha}, the committed golden order is {r.expected_sha}"
        for r in results
        if not r.matches
    ]
    assert not differing, "; ".join(differing)
    return results


@pytest.mark.golden_order
@pytest.mark.solver_child
def test_the_reference_projects_plan_to_their_committed_golden_order() -> None:
    # bypass: one committed instance against one blessed hash is an integration check by nature; the properties
    # behind it (generator determinism, hash injectivity) are 06-01's.
    check_golden_orders(os.environ)
