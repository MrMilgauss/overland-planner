"""Slice 03 steps: a full-size trip within budget, limits and Stop (US-06a, US-06b, FR-5.5, FR-5.6).

Everything goes through the driving ports (D115): Calculate, the plan job poll, `POST /api/plan-jobs/{id}/stop`,
the plan runs, the export and `GET /api/diagnostics` (brief §5, kpi-contracts.yaml). Every press, Stop and abnormal
end captures the planning universe before and after (Mandate 8); the Thens read what Marco is shown.

DISTILL's proposals (DELIVER owns the shapes; the steps ask only for what the scenarios need):
- limits: `FEASIBILITY_LIMIT_S`, `OPTIMISATION_LIMIT_S` (brief §12), wall-clock from job start (`FollowingClock`);
- poll payload (D130 field table): `incumbent` (null until a valid route is found), `legs_new`, `legs_cached`,
  `stage_ms` {stage: ms}, `message`, plus `notices` (a list of notices such as "Large project - ...");
- plan run detail: `not_fully_optimised` (`time_limit` | `stopped` | `optimizer_failed` | null, brief §8 run flags),
  `memo_hit`, and `messages` (the user-facing lines of the results: "Planned 60 items in ...", "Reused the identical
  plan of run #N", a Failed run's reason text);
- the offline road map's look-up latency (`MOCK_PLAN` key `latency`), for the Stop / limit during the look-up;
- the I1 reference project, its golden order and the 30-minute PC reference plan: `fixtures/golden/` (slice 03-ops).

"The 60-item project" (D146) is built here, deterministically, when the exact project does not matter: 40 tracks and
20 POIs between the Susa, Chisone and Ubaye valleys, Start "Casa Marco, Torino", End "Briancon" (62 stops). The
scenarios that need *the* reference project, or its golden order, read the committed I1 fixture instead.
Timing scenarios run the production solver adapter with a scripted child (waiver W1, `ScriptedTourSolver`).
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pytest_bdd import given, parsers, then, when

from overland_planner.bootstrap.startup import StartupRefusedError
from tests.acceptance.overland_route_planner_mvp.steps.browser import REPO_ROOT
from tests.acceptance.overland_route_planner_mvp.steps.catalog_steps import (
    add_poi,
    create_project,
    require_success,
    set_anchors,
)
from tests.acceptance.overland_route_planner_mvp.steps.places import FIXTURES, PLACES
from tests.acceptance.overland_route_planner_mvp.steps.plan_steps import (
    BRIANCON,
    FIRST_TRIP,
    HOME,
    PLAN_DEADLINE_S,
    TERMINAL_JOB_STATES,
    calculate_a_plan,
    note_plan_texts,
    prepare_day_trip,
    press_calculate,
)
from tests.acceptance.overland_route_planner_mvp.steps.planner import RemotePlanner, ServerPlanner, optimizer_processes
from tests.acceptance.overland_route_planner_mvp.steps.world import (
    PLANNING_UNIVERSE,
    PlannerWorld,
    assert_error_envelope,
)
from tests.common.predicates import gained
from tests.common.solver_fakes import FollowingClock, ScriptedTourSolver
from tests.common.state_delta import assert_state_delta
from tests.perf.golden_instances import TripData, committed_trip, order_sha256

SIXTY_TRIP = "Tutto quello che ho sempre voluto guidare"
DOLOMITI_2028 = "Dolomiti 2028"
GOLDEN = FIXTURES.parent / "golden"
I1_DENSE = GOLDEN / "i1-dense.json"
I1_REFERENCE = GOLDEN / "i1-dense.reference-30min.json"
BUILDER_SEED = 20261109  # the test-side 60-item builder; the I1/I2 generator of 03-ops uses seed 20261101
LABELS = {  # what Marco reads -> the run flag behind it (brief §8 run flags)
    "not fully optimised (time limit)": "time_limit",
    "not fully optimised (stopped)": "stopped",
    "not fully optimised (optimizer failed)": "optimizer_failed",
}
FAILED_REASONS = {  # a Failed run's text -> its reason code (ADR-015 amendment D122)
    "stopped before a valid route was found": "stopped",
}
LONG_SEARCH_BUDGET = "100000000"  # a real OR-Tools search that is still improving when the scenario acts
STOP_DEADLINE_S = 15.0
AT_ONCE_S = 10.0  # "at once": far below the 600 s feasibility limit, including the child's spawn
GIVEN_DEADLINE_S = 60.0
OPTIMIZER_START_DEADLINE_S = 10.0  # a spawned optimizer child appears shortly after the job reports "solving"
PI_PLAN_DEADLINE_S = 600.0  # a measured plan on the Pi: as long as the default feasibility limit
REAL_SOLVE_DEADLINE_S = 90.0  # a server process spawning its real OR-Tools child until the job is solving
POLL_EVERY_S = 0.1
RUN_TIME = r" (?:\d+ h )?(?:\d+ min )?\d+(?:\.\d+)? s"  # "Planned 60 items in 3 s", "... in 1 min 05 s"
PI_URL_KEY = "PLANNER_PERF_URL"  # set by make perf-pi (slice 03-ops, D96): the planner-perf tunnel on loopback 18080
PERF_REPORT_KEY = "PERF_REPORT"  # set by make perf-pi for the K5 gate: the file its report reads the runs from


# ------------------------------------------------------------------------------------------- the trip data
def synthetic_trip(tracks: int, pois: int) -> TripData:
    """The test-side builder: deterministic, short trails of 3 points and places in the Western Alps."""
    rng = random.Random(BUILDER_SEED)  # noqa: S311 - test data, not security
    built_tracks = []
    for number in range(1, tracks + 1):
        lat, lon = rng.uniform(44.40, 45.70), rng.uniform(6.70, 7.55)
        dlat, dlon = rng.uniform(-0.03, 0.03), rng.uniform(-0.04, 0.04)
        points = tuple((round(lat + dlat * k / 2, 6), round(lon + dlon * k / 2, 6), 1500.0 + 100 * k) for k in range(3))
        built_tracks.append((f"Pista {number:02d}", points))
    built_pois = tuple(
        (f"Punto {number:02d}", round(rng.uniform(44.40, 45.70), 6), round(rng.uniform(6.70, 7.55), 6))
        for number in range(1, pois + 1)
    )
    home, briancon = PLACES[HOME], PLACES[BRIANCON]
    return TripData(
        tuple(built_tracks), built_pois, (home.name, home.lat, home.lon), (briancon.name, briancon.lat, briancon.lon)
    )


def gpx_track(name: str, points: tuple[tuple[float, float, float], ...]) -> bytes:
    rows = "".join(f'    <trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>\n' for lat, lon, ele in points)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="overland-planner DISTILL fixture" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <trk><name>{name}</name><trkseg>\n{rows}  </trkseg></trk>\n</gpx>\n"
    ).encode()


def bring_trip(world: PlannerWorld, name: str, trip: TripData) -> None:
    """Marco creates the project, imports its trail files, adds its places, and sets Start and End."""
    create_project(world, name)
    require_success(world, f"create the project {name!r}")
    assert world.project_id is not None
    files = [(f"{track}.gpx".lower().replace(" ", "-"), gpx_track(track, points)) for track, points in trip.tracks]
    world.note(world.marco().import_track_files(world.project_id, files))
    require_success(world, f"import {len(files)} trail files")
    for poi, lat, lon in (*trip.pois, trip.start, trip.end):
        add_poi(world, poi, lat, lon)
        require_success(world, f"add {poi!r}")
    set_anchors(world, trip.start[0], trip.end[0])
    require_success(world, "set the Start and End")
    included = [item for item in world.items() if item["included"] and item.get("anchor") is None]
    assert len(included) == trip.item_count, f"{len(included)} items Included, expected {trip.item_count}"
    world.scratch["trip"] = trip


def ensure_trip(world: PlannerWorld, items: int = 60) -> None:
    trip: TripData | None = world.scratch.get("trip")
    if trip is None:
        bring_trip(world, SIXTY_TRIP, synthetic_trip(tracks=items - 20, pois=20))
        return
    assert trip.item_count == items, f"the open project has {trip.item_count} items, not {items}"


# ---------------------------------------------------------------------------------------- the plan job
def follow_job(
    world: PlannerWorld, job_id: str, until: Callable[[dict[str, Any]], bool], deadline_s: float
) -> tuple[dict[str, Any], httpx.Response]:
    """Poll the job like the browser does until `until` holds or the deadline passes; returns the last poll."""
    deadline = time.monotonic() + deadline_s
    while True:
        answer = world.marco().plan_job(job_id)
        assert answer.status_code == 200, f"the plan job did not open: {answer.status_code} {answer.text[:300]}"
        job = dict(answer.json())
        note_plan_texts(world, job)
        if until(job) or time.monotonic() >= deadline:
            return job, answer
        time.sleep(POLL_EVERY_S)


def is_terminal(job: dict[str, Any]) -> bool:
    return job["state"] in TERMINAL_JOB_STATES


def ended_or_in(state: str) -> Callable[[dict[str, Any]], bool]:
    """Until the job ended or is in `state`."""
    return lambda job: is_terminal(job) or job["state"] == state


def press(world: PlannerWorld, *, ignore_memo: bool = False) -> None:
    assert world.project_id is not None, "no project is open"
    world.before = world.planning_view()
    answer = world.note(world.marco().calculate(world.project_id, ignore_memo=ignore_memo))
    assert answer.status_code == 202, f"Calculate was not accepted: {answer.status_code} {answer.text[:300]}"
    note_plan_texts(world, answer.json())
    world.scratch["job_id"] = str(answer.json()["job_id"])
    world.scratch["pressed_at"] = time.monotonic()


def finish(world: PlannerWorld, deadline_s: float) -> dict[str, Any]:
    """Wait until the job ends (or the deadline passes, which the Thens report); keep what Marco was shown."""
    job, answer = follow_job(world, world.scratch["job_id"], is_terminal, deadline_s)
    world.scratch["job"] = job
    world.scratch["ended_at"] = time.monotonic()
    world.scratch["plan_run_id"] = job.get("plan_run_id")
    world.response = answer
    world.after = world.planning_view()
    return job


def stop_job(world: PlannerWorld, job_id: str) -> None:
    """Marco presses "Stop and use best so far" (D136: 200 with the current poll payload)."""
    world.before = world.planning_view()
    answer = world.note(world.marco().stop_plan_job(job_id))
    if answer.status_code == 200:
        note_plan_texts(world, answer.json())
    job, _ = follow_job(world, job_id, is_terminal, STOP_DEADLINE_S)
    world.scratch["job"] = job
    world.scratch["plan_run_id"] = job.get("plan_run_id")
    world.after = world.planning_view()
    world.response = answer


def ended_job(world: PlannerWorld) -> dict[str, Any]:
    job: dict[str, Any] = world.scratch["job"]
    assert is_terminal(job), f"the plan is still being worked out: {job}"
    return job


def latest_run(world: PlannerWorld) -> dict[str, Any]:
    job = ended_job(world)
    plan_run_id = job.get("plan_run_id")
    assert plan_run_id, f"the plan ended without a plan run: {job}"
    answer = world.marco().plan_run(str(plan_run_id))
    assert answer.status_code == 200, f"the plan run did not open: {answer.status_code} {answer.text[:300]}"
    detail = dict(answer.json())
    note_plan_texts(world, detail)
    return detail


def run_texts(job: dict[str, Any], detail: dict[str, Any]) -> list[str]:
    texts = [job.get("message"), *(job.get("notices") or ()), *(detail.get("messages") or ())]
    return [text for text in texts if isinstance(text, str)]


def new_run_number(world: PlannerWorld) -> int:
    return len(world.before["project.plan_runs"]) + 1


def assert_labelled(detail: dict[str, Any], label: str) -> None:
    assert label in LABELS, f"unknown label {label!r}"
    shown = detail.get("not_fully_optimised")
    assert shown == LABELS[label], f"plan run #{detail['number']} is labelled {shown!r}, expected {LABELS[label]!r}"


def assert_ready(detail: dict[str, Any]) -> None:
    status, reason = detail["status"], detail.get("failure_reason")
    assert status == "ready", f"plan run #{detail['number']} is {status}: {reason}"


def stop_names(detail: dict[str, Any]) -> list[str]:
    return [stop["name"] for stop in detail["stops"]]


def use_scripted_optimizer(world: PlannerWorld, *scripts: str, life_s: float | None = None) -> ScriptedTourSolver:
    assert world.planner is None, "the optimizer is chosen before the planner starts"
    extra = {} if life_s is None else {"life_s": life_s}
    solver = ScriptedTourSolver(scripts, world.tmp_path / "solver", **extra)
    world.tour_solver = solver
    world.clock = FollowingClock()
    return solver


def scripted(world: PlannerWorld) -> ScriptedTourSolver:
    assert isinstance(world.tour_solver, ScriptedTourSolver), "the scenario has no scripted optimizer"
    return world.tour_solver


def slow_road_look_up(world: PlannerWorld, delay_s: float) -> None:
    """The offline road map answers the first 1,000 pairs at once, then each further look-up call after `delay_s`."""
    road_map = world.tmp_path / "slow-road-look-up.yaml"
    road_map.write_text(
        "# DISTILL's proposal of the offline road map's look-up latency (slice 03; DELIVER owns the format)\n"
        "detour_factor: 1.3\n"
        "pairs: []\n"
        f"latency: {{answered_at_once_pairs: 1000, then_each_call_s: {delay_s}}}\n",
        encoding="utf-8",
    )
    world.environ["MOCK_PLAN"] = str(road_map)
    world.clock = FollowingClock()
    try:
        world.ensure_planner()
    except StartupRefusedError as refused:
        raise AssertionError(
            f"the planner refused to start with the road look-up latency of the offline road map: {refused!r} "
            "(slice 03 needs the MOCK_PLAN `latency` key, planned for slice 06a)"
        ) from None
    health = world.marco().health()
    assert health.status_code == 200, (
        f"the planner did not accept the road look-up latency of the offline road map: {health.status_code} "
        f"{health.text[:300]}"
    )


def legs_found(job: dict[str, Any]) -> int:
    found = job.get("legs_new")
    assert isinstance(found, int), f"the plan job does not report the road legs found so far: {job}"
    return found


def a_valid_route_is_being_improved(world: PlannerWorld) -> None:
    use_scripted_optimizer(world, "improving", "finish")  # "finish": a later fresh search ends at once
    ensure_trip(world)
    press(world)
    job, _ = follow_job(
        world,
        world.scratch["job_id"],
        lambda j: is_terminal(j) or (j["state"] == "solving" and j.get("incumbent") is not None),
        GIVEN_DEADLINE_S,
    )
    assert job["state"] == "solving" and job.get("incumbent"), f"no valid route is reported while optimising: {job}"


def a_stopped_run(world: PlannerWorld, label: str) -> None:
    a_valid_route_is_being_improved(world)
    stop_job(world, world.scratch["job_id"])
    detail = latest_run(world)
    assert_labelled(detail, label)
    world.scratch["stopped_run"] = (detail["number"], stop_names(detail))


def the_reused_plan_offers_reoptimise(world: PlannerWorld) -> None:
    detail = latest_run_after_existing_press(world)
    number = detail["number"]
    assert detail.get("memo_hit") is True, f"plan run #{number} did not reuse a plan; Re-optimise is offered only then"


def latest_run_after_existing_press(world: PlannerWorld) -> dict[str, Any]:
    """After the shared plan steps' press (`calculate_a_plan`), read the job and its run like `latest_run`."""
    job, _ = follow_job(world, world.scratch["job_id"], is_terminal, PLAN_DEADLINE_S)
    world.scratch["job"] = job
    return latest_run(world)


def a_long_real_optimisation(world: PlannerWorld) -> None:
    """A real planner process and a real OR-Tools search with a budget it cannot finish while the scenario acts."""
    world.environ["SOLVER_BUDGET"] = LONG_SEARCH_BUDGET
    server = ServerPlanner(world.environ, REPO_ROOT)
    world.planner = server
    server.start()
    ensure_trip(world)
    press(world)
    job, _ = follow_job(world, world.scratch["job_id"], ended_or_in("solving"), REAL_SOLVE_DEADLINE_S)
    assert job["state"] == "solving", f"the 60-item plan is not being optimised: {job}"
    world.scratch["sixty"] = (world.project_id, world.scratch["job_id"])


def assert_sixty_continues(world: PlannerWorld) -> None:
    project_id, job_id = world.scratch["sixty"]
    for _ in range(2):
        job, _ = follow_job(world, job_id, lambda j: True, 0)
        assert job["state"] == "solving", f"the 60-item plan stopped being optimised: {job}"
        time.sleep(1.0)
    world.project_id = project_id


def process_tree(root_pid: int) -> str:
    """Every process under `root_pid` as `pid ppid command`, for a failure message."""
    table = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,ppid=,command="], capture_output=True, text=True, check=True)
    rows = [line.split(None, 2) for line in table.stdout.splitlines() if len(line.split(None, 2)) == 3]
    children: dict[int, list[list[str]]] = {}
    for row in rows:
        children.setdefault(int(row[1]), []).append(row)
    lines, pending = [], [root_pid]
    while pending:
        for row in children.get(pending.pop(), []):
            pending.append(int(row[0]))
            lines.append(" ".join(row))
    return "\n".join(lines) or "(none)"


def running_optimizers(root_pid: int, deadline_s: float) -> list[int]:
    """The optimizer children once at least one is up: the job reports "solving" just before its child is spawned."""
    deadline = time.monotonic() + deadline_s
    while not (found := optimizer_processes(root_pid)) and time.monotonic() < deadline:
        time.sleep(POLL_EVERY_S)
    return found


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False)
    return bool(state.stdout.strip()) and not state.stdout.strip().startswith("Z")


def record_perf_run(job: dict[str, Any]) -> None:
    """make perf-pi (06-05, D147): every measured run's terminal state and stage times go to its report."""
    report = os.environ.get(PERF_REPORT_KEY)
    if not report:
        return
    run = {"state": job.get("state"), "stage_ms": job.get("stage_ms"), "retried": job.get("retried")}
    with Path(report).open("a", encoding="utf-8") as runs:
        runs.write(json.dumps(run) + "\n")


def on_the_pi(world: PlannerWorld, trip: TripData) -> None:
    url = os.environ.get(PI_URL_KEY)
    assert url, f"{PI_URL_KEY} is not set: this scenario runs only through make perf-pi (slice 03-ops, D96)"
    world.planner = RemotePlanner(url)
    world.planner.start()
    bring_trip(world, f"__perf {time.strftime('%Y%m%d-%H%M%S')}", trip)  # '__' projects stay out of K1/K7


# ======================================================================================== US-06a (Given)
@given(
    parsers.re(
        r"a project of (?P<items>\d+) items plus Start and End: (?P<tracks>\d+) tracks and (?P<pois>\d+) POIs, "
        r'with Start "(?P<start>[^"]+)" and End "(?P<end>[^"]+)"'
    ),
    converters={"items": int, "tracks": int, "pois": int},
)
def given_the_reference_project_on_the_pi(
    world: PlannerWorld, items: int, tracks: int, pois: int, start: str, end: str
) -> None:
    trip = committed_trip(I1_DENSE)
    shape = (trip.item_count, len(trip.tracks), len(trip.pois), trip.start[0], trip.end[0])
    assert shape == (items, tracks, pois, start, end), f"the I1 fixture is {shape}"
    on_the_pi(world, trip)


@given("its road distances are already known")
def given_its_road_distances_are_already_known(world: PlannerWorld) -> None:
    press(world, ignore_memo=True)  # a first plan fetches every road leg; it is not one of the measured runs
    job = finish(world, PI_PLAN_DEADLINE_S)
    assert job["state"] == "done", f"the warm-up plan did not finish: {job}"


@given("reuse of identical earlier plans is disabled for the measurement")
def given_reuse_is_disabled(world: PlannerWorld) -> None:
    world.scratch["ignore_memo"] = True


@given(
    parsers.re(
        r"the time limits are (?P<feasibility>\d+) seconds to find a route and (?P<optimisation>\d+) seconds to "
        r"improve it"
    ),
    converters={"feasibility": int, "optimisation": int},
)
def given_the_time_limits(world: PlannerWorld, feasibility: int, optimisation: int) -> None:
    world.environ["FEASIBILITY_LIMIT_S"] = str(feasibility)
    world.environ["OPTIMISATION_LIMIT_S"] = str(optimisation)
    world.scratch["deadline_s"] = optimisation + 10.0


@given("the search budget would need longer")
def given_the_search_budget_would_need_longer(world: PlannerWorld) -> None:
    use_scripted_optimizer(world, "improving")


@given(parsers.re(r"a reference plan of the (?P<items>\d+)-item project found with a 30-minute search on a PC"))
def given_a_reference_plan_from_a_long_search(world: PlannerWorld, items: str) -> None:
    trip = committed_trip(I1_DENSE)
    assert I1_REFERENCE.exists(), f"{I1_REFERENCE.relative_to(REPO_ROOT)} does not exist yet (slice 03-ops)"
    reference = json.loads(I1_REFERENCE.read_text(encoding="utf-8"))
    assert trip.item_count == int(items), f"the I1 fixture has {trip.item_count} items"
    world.scratch["reference_road_km"] = float(reference["road_km"])
    on_the_pi(world, trip)


@given("the 60-item project with its road distances already known")
def given_the_sixty_item_project_with_known_distances(world: PlannerWorld) -> None:
    # The offline road map answers every leg without a look-up (brief §6): its distances are known from the start.
    ensure_trip(world, 60)


@given(
    parsers.re(r"a project of (?P<items>\d+) items plus Start and End with its road distances already known"),
    converters={"items": int},
)
def given_a_large_project(world: PlannerWorld, items: int) -> None:
    ensure_trip(world, items)


@given("the committed 60-item reference project and its expected order")
def given_the_committed_reference_project(world: PlannerWorld) -> None:
    trip = committed_trip(I1_DENSE)
    assert trip.expected_order and trip.expected_order_sha256, "the I1 fixture has no expected order"
    assert order_sha256(trip.expected_order) == trip.expected_order_sha256, "the I1 golden hash does not match"
    world.environ.pop("SOLVER_BUDGET", None)  # the default search budget (ADR-014)
    bring_trip(world, "I1 reference", trip)


# ======================================================================================== US-06b (Given)
@given("a plan run of the 60-item project is being optimised and a valid route has been found")
def given_a_valid_route_is_being_improved(world: PlannerWorld) -> None:
    a_valid_route_is_being_improved(world)


@given("a plan run of the 60-item project is being optimised and no valid route has been found yet")
def given_no_valid_route_yet(world: PlannerWorld) -> None:
    use_scripted_optimizer(world, "silent")
    ensure_trip(world)
    press(world)
    job, _ = follow_job(world, world.scratch["job_id"], ended_or_in("solving"), GIVEN_DEADLINE_S)
    assert job["state"] == "solving", f"the plan is not being optimised: {job}"
    assert job.get("incumbent") is None, f"a valid route was already found: {job}"


@given("Marco pressed Recalculate and road legs are still being fetched")
def given_road_legs_are_still_being_fetched(world: PlannerWorld) -> None:
    slow_road_look_up(world, delay_s=60.0)
    ensure_trip(world)
    press(world)
    job, _ = follow_job(
        world,
        world.scratch["job_id"],
        lambda j: is_terminal(j) or (j["state"] == "computing_legs" and (j.get("legs_new") or 0) > 0),
        GIVEN_DEADLINE_S,
    )
    assert job["state"] == "computing_legs" and legs_found(job) > 0, f"no road legs are being fetched: {job}"


@given(
    parsers.re(
        r"the feasibility limit is set to (?P<seconds>\d+) seconds and the optimizer finds no valid route for the "
        r"60-item project in that time"
    ),
    converters={"seconds": int},
)
def given_no_valid_route_within_the_feasibility_limit(world: PlannerWorld, seconds: int) -> None:
    world.environ["FEASIBILITY_LIMIT_S"] = str(seconds)
    use_scripted_optimizer(world, "silent", life_s=seconds + 30.0)
    world.scratch["deadline_s"] = seconds + 15.0


@given("the optimizer finishes its search for the 60-item project without finding any valid route")
def given_the_optimizer_finds_no_route(world: PlannerWorld) -> None:
    use_scripted_optimizer(world, "no_route")


@given(
    parsers.re(
        r"the feasibility limit is set to (?P<seconds>\d+) seconds and the road look-up for the 60-item project "
        r"takes longer"
    ),
    converters={"seconds": int},
)
def given_the_road_look_up_outlasts_the_feasibility_limit(world: PlannerWorld, seconds: int) -> None:
    world.environ["FEASIBILITY_LIMIT_S"] = str(seconds)
    slow_road_look_up(world, delay_s=seconds + 60.0)
    world.scratch["deadline_s"] = seconds + 15.0


@given(parsers.re(r'a plan run was stopped and labelled "(?P<label>[^"]+)"'))
def given_a_plan_run_was_stopped(world: PlannerWorld, label: str) -> None:
    a_stopped_run(world, label)


@given('the latest plan run reused a stopped run\'s plan and offers "Re-optimise (ignore previous result)"')
def given_the_latest_run_reused_a_stopped_plan(world: PlannerWorld) -> None:
    a_stopped_run(world, "not fully optimised (stopped)")
    calculate_a_plan(world)  # Marco recalculates without changing anything (the scenario before)
    the_reused_plan_offers_reoptimise(world)


@given("a plan run of the 60-item project is being optimised")
def given_the_sixty_item_plan_is_being_optimised(world: PlannerWorld) -> None:
    a_long_real_optimisation(world)


@given(parsers.re(r'Marco pressed Calculate on "(?P<project>[^"]+)", which now waits for the optimizer'))
def given_a_second_project_waits_for_the_optimizer(world: PlannerWorld, project: str) -> None:
    assert project == DOLOMITI_2028, f"only {DOLOMITI_2028!r} is set up here"
    create_project(world, project)
    require_success(world, f"create the project {project!r}")
    for name in ("Cortina d'Ampezzo", "Lago di Braies", "Passo Giau", "Misurina"):
        place = PLACES[name]
        add_poi(world, name, place.lat, place.lon)
        require_success(world, f"add {name!r}")
    set_anchors(world, "Cortina d'Ampezzo", "Lago di Braies")
    require_success(world, "set Cortina as Start and Lago di Braies as End")
    press(world)
    world.scratch.setdefault("jobs", {})[project] = (world.project_id, world.scratch["job_id"])
    job, _ = follow_job(world, world.scratch["job_id"], ended_or_in("waiting_for_optimizer"), GIVEN_DEADLINE_S)
    assert job["state"] == "waiting_for_optimizer", f"{project} does not wait for the optimizer: {job}"


@given(
    parsers.re(
        r'Marco planned "(?P<project>[^"]+)" (?P<count>\d+) times this evening, each run having its stage timings '
        r"recorded"
    ),
    converters={"count": int},
)
def given_marco_planned_several_times(world: PlannerWorld, project: str, count: int) -> None:
    assert project == FIRST_TRIP, f"only {FIRST_TRIP!r} has a day trip to plan here"
    prepare_day_trip(world)
    for attempt in range(count):
        press(world, ignore_memo=attempt > 0)  # each a real search, so every run has its stage timings
        job = finish(world, PLAN_DEADLINE_S)
        assert job["state"] == "done", f"plan {attempt + 1} of {count} did not finish: {job}"


# ================================================================================================== When
@when("Marco presses Calculate 10 times on his Raspberry Pi")
def when_marco_presses_calculate_ten_times_on_the_pi(world: PlannerWorld) -> None:
    jobs = []
    for _ in range(10):
        press(world, ignore_memo=bool(world.scratch.get("ignore_memo")))
        jobs.append(finish(world, PI_PLAN_DEADLINE_S))
        record_perf_run(jobs[-1])
    world.scratch["pi_jobs"] = jobs


@when(parsers.re(r"Marco calculates a plan for the (?P<items>\d+)-item project"), converters={"items": int})
def when_marco_calculates_a_plan_for_the_project(world: PlannerWorld, items: int) -> None:
    ensure_trip(world, items)
    press(world)
    finish(world, world.scratch.get("deadline_s", PLAN_DEADLINE_S))


@when("Marco calculates a plan for the same project on the Pi with the default search budget")
def when_marco_calculates_on_the_pi(world: PlannerWorld) -> None:
    press(world, ignore_memo=True)
    finish(world, PI_PLAN_DEADLINE_S)


@when("the planner plans it with the default search budget")
def when_the_planner_plans_it(world: PlannerWorld) -> None:
    assert "SOLVER_BUDGET" not in world.environ, "the planner must use its default search budget"
    press(world)
    finish(world, PLAN_DEADLINE_S)


@when('Marco presses "Stop and use best so far"')
def when_marco_presses_stop(world: PlannerWorld) -> None:
    stop_job(world, world.scratch["job_id"])


@when(parsers.re(r'Marco presses "Stop and use best so far" on "(?P<project>[^"]+)"'))
def when_marco_presses_stop_on(world: PlannerWorld, project: str) -> None:
    project_id, job_id = world.scratch["jobs"][project]
    world.project_id = project_id
    stop_job(world, job_id)


@when("the optimizer stops abnormally")
def when_the_optimizer_stops_abnormally(world: PlannerWorld) -> None:
    world.before = world.planning_view()
    scripted(world).kill_child()
    job, _ = follow_job(world, world.scratch["job_id"], is_terminal, STOP_DEADLINE_S)
    world.scratch["job"] = job
    world.after = world.planning_view()


@when(parsers.re(r'Marco chooses "(?P<action>Re-optimise \(ignore previous result\))"'))
def when_marco_chooses_reoptimise(world: PlannerWorld, action: str) -> None:
    press(world, ignore_memo=True)
    finish(world, PLAN_DEADLINE_S)


@when("the planner is stopped abruptly")
def when_the_planner_is_stopped_abruptly(world: PlannerWorld) -> None:
    server = world.planner
    assert isinstance(server, ServerPlanner), "the planner is not a process of its own here"
    world.scratch["optimizers"] = running_optimizers(server.pid, OPTIMIZER_START_DEADLINE_S)
    if not world.scratch["optimizers"]:
        job, _ = follow_job(world, world.scratch["job_id"], lambda j: True, 0)
        raise AssertionError(
            f"no optimizer process is running under the planner; job {job}; processes:\n{process_tree(server.pid)}"
        )
    server.kill_abruptly()
    world.scratch["killed_at"] = time.monotonic()


@when("Marco presses Recalculate again")
def when_marco_presses_recalculate_again(world: PlannerWorld) -> None:
    press_calculate(world)


@when("Marco opens the diagnostics page")
def when_marco_opens_the_diagnostics_page(world: PlannerWorld) -> None:
    world.scratch["diagnostics"] = world.marco().diagnostics()
    world.scratch["project_diagnostics"] = world.marco().diagnostics(world.project_id)


# ================================================================================================ Then: US-06a
@then(
    parsers.re(r"the solve stage of the slowest of the 10 runs took at most (?P<seconds>\d+) seconds"),
    converters={"seconds": int},
)
def then_the_slowest_solve_stage_fits(world: PlannerWorld, seconds: int) -> None:
    jobs: list[dict[str, Any]] = world.scratch["pi_jobs"]
    assert all(job["state"] == "done" for job in jobs), f"not every run finished: {[j['state'] for j in jobs]}"
    solve_ms = [float((job.get("stage_ms") or {}).get("solve", "nan")) for job in jobs]
    assert all(ms == ms for ms in solve_ms), f"a run does not report its solve stage: {solve_ms}"
    assert max(solve_ms) <= seconds * 1000, f"slowest solve stage {max(solve_ms) / 1000:.1f} s of {solve_ms}"


@then(parsers.re(r"a complete plan is shown within (?P<seconds>\d+) seconds"), converters={"seconds": int})
def then_a_complete_plan_is_shown_within(world: PlannerWorld, seconds: int) -> None:
    detail = latest_run(world)
    assert_ready(detail)
    took = world.scratch["ended_at"] - world.scratch["pressed_at"]
    assert took <= seconds, f"the plan was shown after {took:.1f} s"
    trip: TripData = world.scratch["trip"]
    expected = sorted([name for name, _ in trip.tracks] + [name for name, *_ in trip.pois])
    assert sorted(stop_names(detail)[1:-1]) == expected, "the plan does not visit every Included item once"
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((1, "ready"))})


@then(parsers.re(r'it is labelled "(?P<label>[^"]+)"'))
def then_it_is_labelled(world: PlannerWorld, label: str) -> None:
    detail = latest_run(world)
    assert_ready(detail)
    assert_labelled(detail, label)


@then(parsers.re(r'the results show "(?P<text>[^"]+)" followed by the run time'))
def then_the_results_show_the_run_time(world: PlannerWorld, text: str) -> None:
    detail = latest_run(world)
    assert_ready(detail)
    shown = [t for t in run_texts(ended_job(world), detail) if t.startswith(text)]
    assert shown, f"the results do not show {text!r}: {run_texts(ended_job(world), detail)}"
    assert re.fullmatch(RUN_TIME, shown[0][len(text) :]), f"no run time after {text!r}: {shown[0]!r}"


@then("the plan is calculated")
def then_the_plan_is_calculated(world: PlannerWorld) -> None:
    detail = latest_run_after_existing_press(world)
    trip: TripData = world.scratch["trip"]
    assert_ready(detail)
    assert len(detail["stops"]) == trip.item_count + 2, f"{len(detail['stops'])} stops for {trip.item_count} items"


@then("the order is exactly the expected order")
def then_the_order_is_the_expected_order(world: PlannerWorld) -> None:
    detail = latest_run(world)
    trip: TripData = world.scratch["trip"]
    names = stop_names(detail)
    assert names == list(trip.expected_order), f"the order differs from the golden order: {names}"
    assert order_sha256(names) == trip.expected_order_sha256


@then(parsers.re(r"its road km is within (?P<percent>\d+)% of the reference plan"), converters={"percent": int})
def then_its_road_km_is_within(world: PlannerWorld, percent: int) -> None:
    detail = latest_run(world)
    reference = world.scratch["reference_road_km"]
    road_km = float(detail["totals"]["road_km"])
    assert (road_km - reference) / reference <= percent / 100, f"{road_km:.1f} km against {reference:.1f} km"


# ================================================================================================ Then: US-06b
@then("the best route found so far is shown")
def then_the_best_route_so_far_is_shown(world: PlannerWorld) -> None:
    detail = latest_run(world)
    assert_ready(detail)
    incumbents = scripted(world).incumbents()
    assert incumbents, "the optimizer never found a route"
    name_of = {str(item["id"]): item["name"] for item in world.items()}
    best = [name_of[item_id] for item_id in incumbents[-1]]
    assert stop_names(detail) == best, f"the plan shown is not the best route found so far: {stop_names(detail)}"
    assert_state_delta(
        world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((new_run_number(world), "ready"))}
    )


@then(parsers.re(r'the plan run fails with "(?P<text>[^"]+)"'))
def then_the_plan_run_fails_with(world: PlannerWorld, text: str) -> None:
    job = ended_job(world)
    number = new_run_number(world)
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((number, "failed"))})
    detail = latest_run(world)
    assert detail.get("failure_reason") == FAILED_REASONS[text], f"fails with {detail.get('failure_reason')!r}"
    assert text in world.seen_messages, f"{text!r} not shown; Marco saw {world.seen_messages}"
    assert job.get("plan_run_id") == detail["id"]


@then("the road legs found so far are kept for the next Recalculate")
def then_the_road_legs_are_kept(world: PlannerWorld) -> None:
    found = legs_found(ended_job(world))
    assert found > 0, "no road leg had been found when the plan ended"
    press(world)
    job, _ = follow_job(
        world, world.scratch["job_id"], lambda j: is_terminal(j) or j.get("legs_cached") is not None, STOP_DEADLINE_S
    )
    cached = job.get("legs_cached")
    assert isinstance(cached, int) and cached >= found, f"{found} legs were found, the next plan reuses {cached}"
    world.marco().stop_plan_job(world.scratch["job_id"])


@then(parsers.re(r'he sees "(?P<text>[^"]*#N[^"]*)", N being the new run\'s number'))
def then_he_sees_the_new_runs_number(world: PlannerWorld, text: str) -> None:
    job = ended_job(world)
    number = new_run_number(world)
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((number, "failed"))})
    detail = latest_run(world)
    assert detail.get("failure_reason") == "timeout", f"plan run #{number} fails with {detail.get('failure_reason')!r}"
    message = text.replace("#N", f"#{number}")
    assert message in world.seen_messages, f"{message!r} not shown; Marco saw {world.seen_messages}"
    assert job["state"] == "done"


@then(parsers.re(r'the plan run fails at once with reason "(?P<reason>[^"]+)"'))
def then_the_plan_run_fails_at_once(world: PlannerWorld, reason: str) -> None:
    ended_job(world)
    took = world.scratch["ended_at"] - world.scratch["pressed_at"]
    assert took <= AT_ONCE_S, f"the plan run failed only after {took:.1f} s"
    assert_state_delta(
        world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((new_run_number(world), "failed"))}
    )
    detail = latest_run(world)
    assert detail.get("failure_reason") == reason, f"fails with {detail.get('failure_reason')!r}"


@then("no itinerary is offered")
def then_no_itinerary_is_offered(world: PlannerWorld) -> None:
    detail = latest_run(world)
    assert detail["stops"] == [] and detail["totals"] is None, f"a Failed run shows an itinerary: {detail['stops']}"
    export = world.marco().export_gpx(str(detail["id"]))
    assert export.status_code == 422, f"a Failed run can be exported: {export.status_code}"
    assert_error_envelope(export)


@then(parsers.re(r'he sees the identical plan at once, labelled "(?P<label>[^"]+)"'))
def then_he_sees_the_identical_plan_at_once(world: PlannerWorld, label: str) -> None:
    stopped_number, stopped_stops = world.scratch["stopped_run"]
    detail = latest_run_after_existing_press(world)
    job = ended_job(world)
    assert_state_delta(
        world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((stopped_number + 1, "ready"))}
    )
    assert stop_names(detail) == stopped_stops, f"the plan differs from plan run #{stopped_number}"
    assert job.get("memo_hit") is True and float(job["elapsed_s"]) <= AT_ONCE_S, f"not reused at once: {job}"
    assert_labelled(detail, label)


@then(parsers.re(r'it says "(?P<text>[^"]+)" followed by the stopped run\'s number'))
def then_it_says_reused_with_the_stopped_runs_number(world: PlannerWorld, text: str) -> None:
    stopped_number, _ = world.scratch["stopped_run"]
    texts = run_texts(ended_job(world), latest_run(world))
    assert f"{text} #{stopped_number}" in texts, f"the results say {texts}"


@then(parsers.re(r'"(?P<action>Re-optimise \(ignore previous result\))" is offered'))
def then_reoptimise_is_offered(world: PlannerWorld, action: str) -> None:
    detail = latest_run(world)
    assert detail.get("memo_hit") is True, f"{action!r} is offered on a reused plan only; plan run shows {detail}"


@then("a fresh search runs and creates a new plan run")
def then_a_fresh_search_runs(world: PlannerWorld) -> None:
    job = ended_job(world)
    assert job.get("ignore_memo") is True and job.get("memo_hit") is False, f"not a fresh search: {job}"
    assert scripted(world).calls == 2, f"the optimizer was asked {scripted(world).calls} times, expected 2"
    assert_state_delta(
        world.before, world.after, PLANNING_UNIVERSE, {"project.plan_runs": gained((new_run_number(world), "ready"))}
    )


@then(parsers.re(r'the new run does not say "(?P<text>[^"]+)"'))
def then_the_new_run_does_not_say(world: PlannerWorld, text: str) -> None:
    texts = run_texts(ended_job(world), latest_run(world))
    assert not [t for t in texts if t.startswith(text)], f"the new run says {texts}"


@then(parsers.re(r"no optimizer process is left running after (?P<seconds>\d+) seconds"), converters={"seconds": int})
def then_no_optimizer_process_is_left(world: PlannerWorld, seconds: int) -> None:
    time.sleep(max(0.0, world.scratch["killed_at"] + seconds - time.monotonic()))
    left = [pid for pid in world.scratch["optimizers"] if is_running(pid)]
    assert not left, f"optimizer processes still running {seconds} s after the planner stopped: {left}"


@then("after the planner starts again no plan run was created for the interrupted plan")
def then_no_plan_run_after_restart(world: PlannerWorld) -> None:
    assert world.planner is not None
    world.planner.stop()
    world.planner.start()
    assert world.planning_view()["project.plan_runs"] == (), "the interrupted plan left a plan run"


@then("the running plan continues")
def then_the_running_plan_continues(world: PlannerWorld) -> None:
    assert_sixty_continues(world)


@then(parsers.re(r'no plan run is created for "(?P<project>[^"]+)"'))
def then_no_plan_run_is_created_for(world: PlannerWorld, project: str) -> None:
    job = ended_job(world)
    assert job.get("plan_run_id") is None, f"{project} got a plan run: {job}"
    assert_state_delta(world.before, world.after, PLANNING_UNIVERSE, {})
    assert world.after["project.plan_runs"] == (), f"{project} has plan runs {world.after['project.plan_runs']}"


@then("the 60-item plan continues")
def then_the_sixty_item_plan_continues(world: PlannerWorld) -> None:
    assert_sixty_continues(world)


# ================================================================================================ Then: KPIs
def diagnostics(world: PlannerWorld, key: str = "diagnostics") -> dict[str, Any]:
    answer: httpx.Response = world.scratch[key]
    assert answer.status_code == 200, f"the diagnostics did not open: {answer.status_code} {answer.text[:300]}"
    return dict(answer.json())


def all_zero(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value) and all(all_zero(v) for v in value.values())
    return value == 0


@then("he sees the 95th percentile planning time of each stage, counting every run")
def then_he_sees_the_stage_p95(world: PlannerWorld) -> None:
    shown = diagnostics(world)
    stages = (shown.get("k5") or {}).get("stage_p95_s")
    assert isinstance(stages, dict) and "solve" in stages, f"no planning time per stage: {shown.get('k5')}"
    assert all(isinstance(v, int | float) for v in stages.values()), f"stage times: {stages}"
    counted = sum((shown.get("jobs_by_terminal_state_30d") or {}).values())
    assert counted == len(world.before["project.plan_runs"]) + 1, f"{counted} runs counted"


@then("he sees how many runs were retried, shown separately")
def then_he_sees_the_retried_runs(world: PlannerWorld) -> None:
    shown = diagnostics(world)
    assert shown.get("retried_jobs_30d") == 0, f"retried runs: {shown.get('retried_jobs_30d')!r}"
    assert "retried_jobs" in (shown.get("k5") or {}), f"retried runs are not shown per size band: {shown.get('k5')}"


@then(parsers.re(r"he sees (?P<count>\d+) variants tried for that project today"), converters={"count": int})
def then_he_sees_the_variants(world: PlannerWorld, count: int) -> None:
    k7 = diagnostics(world, "project_diagnostics").get("k7")
    runs = k7.get("runs_per_project_day") if isinstance(k7, dict) else None
    today = runs.get("max") if isinstance(runs, dict) else runs
    assert today == count, f"variants tried today: {k7!r}"


@then(
    parsers.re(
        r"he sees (?P<violations>\d+) plans that broke a hard rule and (?P<omissions>\d+) plans that left an item "
        r"out of the report"
    ),
    converters={"violations": int, "omissions": int},
)
def then_he_sees_no_broken_rules(world: PlannerWorld, violations: int, omissions: int) -> None:
    shown = diagnostics(world)
    k2 = (shown.get("k2") or {}).get("invariant_violations")
    k3 = (shown.get("k3") or {}).get("report_omissions")
    assert k2 is not None and k3 is not None, f"k2 {shown.get('k2')!r}, k3 {shown.get('k3')!r}"
    assert (violations, omissions) == (0, 0), "only zero counts are seeded here"
    assert all_zero(k2) and all_zero(k3), f"k2 {k2!r}, k3 {k3!r}"
