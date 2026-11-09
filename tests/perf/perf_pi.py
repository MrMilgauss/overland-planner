"""The perf-pi measurement and its report (slice 03-ops, 06-05; D96, D135, D146, D147, D159, D177, D223 d).

    uv run python -m tests.perf.perf_pi report  --runs RUNS.jsonl --n 10 --items 60 --out REPORT.json
    uv run python -m tests.perf.perf_pi measure --n 30 --items 70 [--points 20000] --out REPORT.json

Run by deploy/scripts/perf-pi.sh on the Mac, against planner-perf through the ssh tunnel (PLANNER_PERF_URL, with
PLANNER_PERF_USER and PLANNER_PERF_PASSWORD when the Pi's .env sets a household password). `report` turns the runs the
@pi scenario appended to PERF_REPORT into the report; `measure` seeds the generated I1 variant as '__perf <timestamp>',
plans it once to warm the road legs and then N times with ignore_memo, and writes the report of those N runs.

Every measured run counts (D147, D177): failed, stopped or retried ones included. For each stage the report gives the
slowest and the nearest-rank p95 of all N runs. A verdict is given only for the two gates, both with N = 10 at 60 items:
slowest solve <= 55 s (US-06a, D159) with the committed 12 points per track, and slowest guard_persist <= 3 s with
20,000 points per track (D135, D223 d); every other mode (N = 30, ITEMS = 70, D146) reports without a verdict. The exit
code is 1 when a gate is missed or a run did not finish, else 0.
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
GUARD_PERSIST_LIMIT_MS = 3_000
PLAN_DEADLINE_S = 600.0
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


def _read_runs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [run_record(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.perf.perf_pi", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("report", "measure"))
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--items", type=int, required=True)
    parser.add_argument("--points", type=int, default=None)
    parser.add_argument("--runs", type=Path, help="report: the runs the @pi scenario appended to PERF_REPORT")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "report":
        if arguments.runs is None:
            parser.error("report needs --runs")
        runs = _read_runs(arguments.runs)
    else:
        url = os.environ.get(URL_KEY)
        if not url:
            parser.error(f"measure needs {URL_KEY} (make perf-pi sets it)")
        runs = measure(url, n=arguments.n, items=arguments.items, points=arguments.points)
    report = build_report(runs, n=arguments.n, items=arguments.items, points=arguments.points)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"perf-pi: report written to {arguments.out}")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
