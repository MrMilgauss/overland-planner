"""The perf-pi measurement and its report (slice 03-ops, 06-05; D96, D135, D146, D147, D159, D177, D223 d).

    uv run python -m tests.perf.perf_pi report  --runs RUNS.jsonl --n 10 --items 60 --out REPORT.json
    uv run python -m tests.perf.perf_pi measure --n 30 --items 70 [--points 20000] --out REPORT.json
    uv run python -m tests.perf.perf_pi e2e-seed   --items 60 --project-file PROJECT
    uv run python -m tests.perf.perf_pi e2e-run    --project-file PROJECT --out RUNS.jsonl
    uv run python -m tests.perf.perf_pi e2e-report --runs RUNS.jsonl --n 10 --items 60 --out REPORT.json

Run by deploy/scripts/perf-pi.sh on the Mac, against planner-perf through the ssh tunnel (PLANNER_PERF_URL, with
PLANNER_PERF_USER and PLANNER_PERF_PASSWORD when the Pi's .env sets a household password). `report` turns the runs the
@pi scenario appended to PERF_REPORT into the report; `measure` seeds the generated I1 variant as '__perf <timestamp>',
plans it once to warm the road legs and then N times with ignore_memo, and writes the report of those N runs.

Every measured run counts (D147, D177): failed, stopped or retried ones included. For each stage the report gives the
slowest and the nearest-rank p95 of all N runs. A verdict is given only for the two gates, both with N = 10 at 60 items:
slowest solve <= 55 s (US-06a, D159) with the committed 12 points per track, and slowest guard_persist <= 3 s with
20,000 points per track (D135, D223 d); every other mode (N = 30, ITEMS = 70, D146) reports without a verdict. The exit
code is 1 when a gate is missed or a run did not finish, else 0.

MODE=e2e (D236, slice 06a-ops): `e2e-seed` seeds the 60-item I1 project once; `e2e-run` presses Calculate with
ignore_memo on a planner-perf that perf-pi.sh has just recreated (cold) and appends one run to RUNS: the clock stops
when the planner has answered `GET /api/plan-runs/{id}/geometry` (slice 09) or, while that path answers 404, when the
stored plan has been read back (`GET /api/plan-runs/{id}`); each run and the report say which end was measured. The
e2e gate (N = 10, ITEMS = 60): slowest e2e <= 180 s and slowest solve <= 55 s; every run counts (D147, D177).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

STAGES = ("snapshot", "matrix", "reach_model", "solve", "guard_persist")
GATE_RUNS = 10
GATE_ITEMS = 60
GUARD_POINTS = 20_000
SOLVE_LIMIT_MS = 55_000
GUARD_PERSIST_LIMIT_MS = 5_000  # D230 (user, 2026-11-10): about 4.5 s accepted on 20,000-point tracks; was 3 s (D135)
E2E_LIMIT_S = 180
HEAVY_SECOND_PASS_PAIRS = 700  # D147, D177: runs above it are counted and reported, never excluded
PLAN_DEADLINE_S = 600.0
POLL_EVERY_S = 0.5
URL_KEY = "PLANNER_PERF_URL"

Run = Mapping[str, Any]


def nearest_rank(values: Sequence[float], percent: int) -> float | None:
    """The value at rank ceil(percent/100 * n) of the sorted values (nearest-rank method)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(percent * len(ordered) / 100) - 1]


def gate_of(n: int, items: int, points: int | None) -> dict[str, Any] | None:
    if n != GATE_RUNS or items != GATE_ITEMS:
        return None
    if points is None:
        return {"stage": "solve", "limit_ms": SOLVE_LIMIT_MS}
    if points == GUARD_POINTS:
        return {"stage": "guard_persist", "limit_ms": GUARD_PERSIST_LIMIT_MS}
    return None


def build_report(runs: Sequence[Run], *, n: int, items: int, points: int | None) -> dict[str, Any]:
    values = {stage: [r["stage_ms"][stage] for r in runs if stage in (r.get("stage_ms") or {})] for stage in STAGES}
    gate = gate_of(n, items, points)
    return {
        "n": n,
        "items": items,
        "points_per_track": points,
        "runs": [dict(r) for r in runs],
        "slowest_ms": {stage: max(v) if v else None for stage, v in values.items()},
        "p95_ms": {stage: nearest_rank(v, 95) for stage, v in values.items()},
        "gate": gate,
        "verdict": None if gate is None else _verdict(runs, n, gate),
    }


def _verdict(runs: Sequence[Run], n: int, gate: Mapping[str, Any]) -> str:
    stage = gate["stage"]
    timed = [r["stage_ms"][stage] for r in runs if r.get("state") == "done" and stage in (r.get("stage_ms") or {})]
    every_run_finished = len(runs) == n and len(timed) == n
    return "pass" if every_run_finished and max(timed) <= gate["limit_ms"] else "fail"


def exit_code(report: Mapping[str, Any]) -> int:
    finished = all(run.get("state") == "done" for run in report["runs"]) and len(report["runs"]) == report["n"]
    return 0 if finished and report["verdict"] != "fail" else 1


def run_record(job: Mapping[str, Any]) -> dict[str, Any]:
    """What a measured run keeps of its last poll: its terminal state, its stage times, whether it was retried."""
    return {"state": job.get("state"), "stage_ms": dict(job.get("stage_ms") or {}), "retried": job.get("retried")}


def e2e_record(job: Mapping[str, Any], e2e_s: float, end: str) -> dict[str, Any]:
    """One cold run: how it ended, its client-side seconds, and what the last poll said of its stages and legs."""
    return {
        "state": job.get("state"),
        "e2e_s": round(e2e_s, 2),
        "stage_ms": dict(job.get("stage_ms") or {}),
        "legs_new": job.get("legs_new"),
        "legs_cached": job.get("legs_cached"),
        "retried": job.get("retried"),
        "second_pass_pairs": job.get("second_pass_pairs"),
        "end": end,
    }


def build_e2e_report(runs: Sequence[Run], *, n: int, items: int) -> dict[str, Any]:
    solves = [r["stage_ms"]["solve"] for r in runs if "solve" in (r.get("stage_ms") or {})]
    seconds = [r["e2e_s"] for r in runs if r.get("e2e_s") is not None]
    ends = {r.get("end") for r in runs}
    gated = n == GATE_RUNS and items == GATE_ITEMS
    slowest_e2e, slowest_solve = (max(seconds) if seconds else None), (max(solves) if solves else None)
    every_run_finished = len(runs) == n and len(solves) == n and all(r.get("state") == "done" for r in runs)
    within = (
        every_run_finished
        and slowest_e2e is not None
        and slowest_e2e <= E2E_LIMIT_S
        and slowest_solve is not None
        and slowest_solve <= SOLVE_LIMIT_MS
    )
    return {
        "mode": "e2e",
        "n": n,
        "items": items,
        "end": ends.pop() if len(ends) == 1 else "mixed",
        "runs": [dict(r) for r in runs],
        "slowest_e2e_s": slowest_e2e,
        "slowest_solve_ms": slowest_solve,
        "retried_runs": sum(1 for r in runs if r.get("retried")),
        "heavy_runs": sum(1 for r in runs if (r.get("second_pass_pairs") or 0) > HEAVY_SECOND_PASS_PAIRS),
        "gate": {"e2e_s": E2E_LIMIT_S, "solve_ms": SOLVE_LIMIT_MS} if gated else None,
        "verdict": ("pass" if within else "fail") if gated else None,
    }


def e2e_summary(report: Mapping[str, Any]) -> str:
    lines = [f"perf-pi e2e: N={report['n']} ITEMS={report['items']}, measured to: {report['end']}"]
    for number, run in enumerate(report["runs"], start=1):
        solve = (run.get("stage_ms") or {}).get("solve")
        lines.append(
            f"  run {number:2d}: {run.get('state')}, e2e {run.get('e2e_s')} s, solve {solve} ms, "
            f"legs new {run.get('legs_new')} cached {run.get('legs_cached')}, retried {run.get('retried')}, "
            f"second pass pairs {run.get('second_pass_pairs')}"
        )
    lines.append(f"  slowest e2e {report['slowest_e2e_s']} s, slowest solve {report['slowest_solve_ms']} ms")
    lines.append(
        f"  retried runs {report['retried_runs']}, runs over {HEAVY_SECOND_PASS_PAIRS} pairs {report['heavy_runs']}"
    )
    lines.append(f"  verdict: {report['verdict'] or 'none (this mode only reports)'}")
    return "\n".join(lines)


def summary(report: Mapping[str, Any]) -> str:
    def seconds(ms: float | None) -> str:
        return "-" if ms is None else f"{ms / 1000:.2f} s"

    lines = [f"perf-pi: N={report['n']} ITEMS={report['items']} POINTS={report['points_per_track'] or 'committed'}"]
    for number, run in enumerate(report["runs"], start=1):
        retried = " (retried)" if run.get("retried") else ""
        lines.append(f"  run {number:2d}: {run.get('state')}{retried}, solve {seconds(run['stage_ms'].get('solve'))}")
    for stage in STAGES:
        slowest, p95 = report["slowest_ms"][stage], report["p95_ms"][stage]
        lines.append(f"  {stage:13s} slowest {seconds(slowest)}, p95 {seconds(p95)}")
    gate = report["gate"]
    if gate is None:
        lines.append("  verdict: none (this mode only reports)")
    else:
        lines.append(f"  verdict: {report['verdict']} (slowest {gate['stage']} <= {gate['limit_ms'] / 1000:g} s)")
    return "\n".join(lines)


def measure(url: str, *, n: int, items: int, points: int | None) -> list[dict[str, Any]]:
    """Seed the I1 variant on the planner at `url`, warm it once, then plan it n times with ignore_memo."""
    from tests.acceptance.overland_route_planner_mvp.steps import performance_steps as steps
    from tests.acceptance.overland_route_planner_mvp.steps.planner import RemotePlanner
    from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld
    from tests.common.fakes import FakeClock, FakeMountTable
    from tests.perf.golden_instances import I1_DENSE, POINTS_PER_TRACK, committed_trip, write

    with tempfile.TemporaryDirectory(prefix="perf-pi-") as folder:
        scratch = Path(folder)
        (fixture, *_) = write(scratch, I1_DENSE, items=items, points_per_track=points or POINTS_PER_TRACK)
        trip = committed_trip(fixture)
        world = PlannerWorld(scratch, scratch, {}, FakeClock(), FakeMountTable())
        planner = RemotePlanner(url)
        world.planner = planner
        planner.start()
        try:
            steps.bring_trip(world, f"__perf {time.strftime('%Y%m%d-%H%M%S')}", trip)
            runs = []
            for attempt in range(n + 1):  # attempt 0 fetches every road leg and is not measured
                steps.press(world, ignore_memo=True)
                job = steps.finish(world, PLAN_DEADLINE_S)
                if attempt:
                    runs.append(run_record(job))
            return runs
        finally:
            world.shutdown()


def e2e_seed(url: str, *, items: int, project_file: Path) -> None:
    """Seed the committed I1 (real Western Alps places) as one project and keep its id in `project_file`."""
    from tests.acceptance.overland_route_planner_mvp.steps import performance_steps as steps
    from tests.acceptance.overland_route_planner_mvp.steps.planner import RemotePlanner
    from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld
    from tests.common.fakes import FakeClock, FakeMountTable
    from tests.perf.golden_instances import I1_DENSE, POINTS_PER_TRACK, committed_trip, write

    with tempfile.TemporaryDirectory(prefix="perf-pi-") as folder:
        scratch = Path(folder)
        (fixture, *_) = write(scratch, I1_DENSE, items=items, points_per_track=POINTS_PER_TRACK)
        world = PlannerWorld(scratch, scratch, {}, FakeClock(), FakeMountTable())
        planner = RemotePlanner(url)
        world.planner = planner
        planner.start()
        try:
            steps.bring_trip(world, f"__perf e2e {time.strftime('%Y%m%d-%H%M%S')}", committed_trip(fixture))
            project_file.write_text(f"{world.project_id}\n", encoding="utf-8")
        finally:
            world.shutdown()


def e2e_run(url: str, *, project_file: Path) -> dict[str, Any]:
    """One cold run on the seeded project: Calculate with ignore_memo to the answer that ends the measurement."""
    from tests.acceptance.overland_route_planner_mvp.steps.performance_steps import is_terminal
    from tests.acceptance.overland_route_planner_mvp.steps.planner import RemotePlanner

    planner = RemotePlanner(url)
    planner.start()
    try:
        marco = planner.session()
        project_id = project_file.read_text(encoding="utf-8").strip()
        started = time.monotonic()
        answer = marco.calculate(project_id, ignore_memo=True)
        if answer.status_code != 202:
            return e2e_record(
                {"state": f"calculate_{answer.status_code}"}, time.monotonic() - started, "plan_read_back"
            )
        job_id = str(answer.json()["job_id"])
        deadline = started + PLAN_DEADLINE_S
        while True:
            job = dict(marco.plan_job(job_id).json())
            if is_terminal(job) or time.monotonic() >= deadline:
                break
            time.sleep(POLL_EVERY_S)
        end = "plan_read_back"
        if job.get("state") == "done" and job.get("plan_run_id"):
            run_id = job["plan_run_id"]
            geometry = marco._request("GET", f"/api/plan-runs/{run_id}/geometry")
            if geometry.status_code == 200:
                end = "geometry"
            elif geometry.status_code != 404 or marco.plan_run(str(run_id)).status_code != 200:
                job = {**job, "state": "failed"}
        return e2e_record(job, time.monotonic() - started, end)
    finally:
        planner.stop()


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_runs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [run_record(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.perf.perf_pi", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("report", "measure", "e2e-seed", "e2e-run", "e2e-report"))
    parser.add_argument("--n", type=int)
    parser.add_argument("--items", type=int)
    parser.add_argument("--points", type=int, default=None)
    parser.add_argument("--runs", type=Path, help="report: the runs the @pi scenario appended to PERF_REPORT")
    parser.add_argument("--project-file", type=Path, help="e2e-seed writes, e2e-run reads the seeded project's id")
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args(argv)
    command = arguments.command
    needs = {
        "report": ("n", "items", "runs", "out"),
        "measure": ("n", "items", "out"),
        "e2e-seed": ("items", "project_file"),
        "e2e-run": ("project_file", "out"),
        "e2e-report": ("n", "items", "runs", "out"),
    }[command]
    for name in needs:
        if getattr(arguments, name) is None:
            parser.error(f"{command} needs --{name.replace('_', '-')}")
    if command in ("measure", "e2e-seed", "e2e-run") and not os.environ.get(URL_KEY):
        parser.error(f"{command} needs {URL_KEY} (make perf-pi sets it)")
    if command == "e2e-seed":
        e2e_seed(os.environ[URL_KEY], items=arguments.items, project_file=arguments.project_file)
        return 0
    if command == "e2e-run":
        run = e2e_run(os.environ[URL_KEY], project_file=arguments.project_file)
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        with arguments.out.open("a", encoding="utf-8") as sink:
            sink.write(json.dumps(run) + "\n")
        print(f"perf-pi e2e: run {run['state']} in {run['e2e_s']} s (ends at {run['end']})")
        return 0
    if command == "e2e-report":
        report = build_e2e_report(_read_lines(arguments.runs), n=arguments.n, items=arguments.items)
        text = e2e_summary(report)
    else:
        runs = (
            _read_runs(arguments.runs)
            if command == "report"
            else measure(os.environ[URL_KEY], n=arguments.n, items=arguments.items, points=arguments.points)
        )
        report = build_report(runs, n=arguments.n, items=arguments.items, points=arguments.points)
        text = summary(report)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(text)
    print(f"perf-pi: report written to {arguments.out}")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
