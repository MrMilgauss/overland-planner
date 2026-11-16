"""The perf-pi report (06-05; D147, D159, D177, D135, D223 d): every measured run counts.

Property: for any N measured runs (states, stage times, retried flags) the report keeps every run; the slowest and the
nearest-rank p95 of each stage are those of all N; the verdict is pass iff N = 10, every run is done and the slowest
gated stage is within its limit (solve <= 55 s at 60 items; guard_persist <= 3 s at 60 items of 20,000 points per
track); any other mode reports without a verdict.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.common.state_delta import assert_state_delta, set_to
from tests.perf.perf_pi import STAGES, build_e2e_report, build_report, exit_code

STATES = ("done", "failed", "stopped", "timed_out")
UNIVERSE = {"n", "items", "points_per_track", "runs", "slowest_ms", "p95_ms", "gate", "verdict"}

stage_ms = st.integers(min_value=0, max_value=120_000)
run = st.fixed_dictionaries(
    {
        "state": st.sampled_from(STATES),
        "stage_ms": st.dictionaries(st.sampled_from(STAGES), stage_ms),  # a failed run may miss stages
        "retried": st.booleans(),
    }
)
done_run = st.fixed_dictionaries(
    {
        "state": st.just("done"),
        "stage_ms": st.fixed_dictionaries(dict.fromkeys(STAGES, stage_ms)),
        "retried": st.booleans(),
    }
)
runs = st.one_of(
    st.lists(done_run, min_size=10, max_size=10),  # the gate modes, mostly finished
    st.lists(st.one_of(done_run, run), min_size=10, max_size=10),
    st.lists(st.one_of(done_run, run), min_size=1, max_size=30),
)


def nearest_rank_p95(values: list[int]) -> int | None:
    """Oracle, from the definition: the smallest observed value with at least 95 % of the values at or below it."""
    if not values:
        return None
    return min(v for v in values if 100 * sum(1 for x in values if x <= v) >= 95 * len(values))


def expected_gate(n: int, items: int, points: int | None) -> tuple[str, int] | None:
    if n != 10 or items != 60:
        return None
    if points is None:
        return "solve", 55_000  # US-06a, D159: slowest of 10
    if points == 20_000:
        return "guard_persist", 5_000  # D135, D223 d, D230: about 4.5 s accepted for 20,000-point tracks
    return None


@given(measured=runs, items=st.sampled_from((60, 70)), points=st.sampled_from((None, 20_000, 12)))
@settings(max_examples=200, deadline=None)
def test_every_run_counts_and_the_verdict_follows_the_gate(
    measured: list[dict[str, Any]], items: int, points: int | None
) -> None:
    n = len(measured)
    values = {stage: [r["stage_ms"][stage] for r in measured if stage in r["stage_ms"]] for stage in STAGES}
    gate = expected_gate(n, items, points)
    if gate is None:
        verdict = None
    else:
        stage, limit = gate
        finished = all(r["state"] == "done" and stage in r["stage_ms"] for r in measured)
        verdict = "pass" if finished and max(values[stage]) <= limit else "fail"
    before: dict[str, Any] = dict.fromkeys(UNIVERSE)

    after = build_report(measured, n=n, items=items, points=points)

    assert_state_delta(
        before,
        after,
        universe=UNIVERSE,
        expected={
            "n": set_to(n),
            "items": set_to(items),
            "points_per_track": set_to(points),
            "runs": set_to(measured),
            "slowest_ms": set_to({stage: max(v) if v else None for stage, v in values.items()}),
            "p95_ms": set_to({stage: nearest_rank_p95(v) for stage, v in values.items()}),
            "gate": set_to(None if gate is None else {"stage": gate[0], "limit_ms": gate[1]}),
            "verdict": set_to(verdict),
        },
        strict=True,
    )


E2E_UNIVERSE = {
    "mode", "n", "items", "end", "runs", "slowest_e2e_s", "slowest_solve_ms", "retried_runs", "heavy_runs", "gate",
    "verdict",
}  # fmt: skip
e2e_run = st.fixed_dictionaries(
    {
        "state": st.sampled_from(STATES),
        "e2e_s": st.floats(min_value=1, max_value=400, allow_nan=False),
        "stage_ms": st.dictionaries(st.sampled_from(STAGES), stage_ms),
        "legs_new": st.integers(0, 2000),
        "legs_cached": st.integers(0, 2000),
        "retried": st.booleans(),
        "second_pass_pairs": st.integers(0, 1500),
        "end": st.sampled_from(("plan_read_back", "geometry")),
    }
)
e2e_done_run = e2e_run.map(
    lambda r: r | {"state": "done", "stage_ms": {**r["stage_ms"], "solve": r["stage_ms"].get("solve", 1)}}
)
e2e_runs = st.one_of(
    st.lists(e2e_done_run, min_size=10, max_size=10),
    st.lists(st.one_of(e2e_done_run, e2e_run), min_size=10, max_size=10),
    st.lists(st.one_of(e2e_done_run, e2e_run), min_size=1, max_size=12),
)


@given(measured=e2e_runs, items=st.sampled_from((60, 70)))
@settings(max_examples=200, deadline=None)
def test_the_e2e_report_counts_every_run_and_the_verdict_follows_the_two_limits(
    measured: list[dict[str, Any]], items: int
) -> None:
    n = len(measured)
    solves = [r["stage_ms"]["solve"] for r in measured if "solve" in r["stage_ms"]]
    slowest_e2e = max(r["e2e_s"] for r in measured)
    slowest_solve = max(solves) if solves else None
    gated = n == 10 and items == 60
    within = (
        all(r["state"] == "done" for r in measured)
        and len(solves) == n
        and slowest_e2e <= 180
        and slowest_solve is not None
        and slowest_solve <= 55_000
    )
    ends = {r["end"] for r in measured}
    before: dict[str, Any] = dict.fromkeys(E2E_UNIVERSE)

    after = build_e2e_report(measured, n=n, items=items)

    assert_state_delta(
        before,
        after,
        universe=E2E_UNIVERSE,
        expected={
            "mode": set_to("e2e"),
            "n": set_to(n),
            "items": set_to(items),
            "end": set_to(ends.pop() if len(ends) == 1 else "mixed"),
            "runs": set_to(measured),
            "slowest_e2e_s": set_to(slowest_e2e),
            "slowest_solve_ms": set_to(slowest_solve),
            "retried_runs": set_to(sum(1 for r in measured if r["retried"])),
            "heavy_runs": set_to(sum(1 for r in measured if r["second_pass_pairs"] > 700)),
            "gate": set_to({"e2e_s": 180, "solve_ms": 55_000} if gated else None),
            "verdict": set_to(("pass" if within else "fail") if gated else None),
        },
        strict=True,
    )


def test_one_failed_run_fails_the_e2e_gate_however_fast_the_others_were() -> None:
    # bypass: the named example of the gate's rule "a failed or unfinished run fails" (D177).
    fast = {
        "state": "done",
        "e2e_s": 90.0,
        "stage_ms": {"solve": 40_000},
        "legs_new": 5,
        "legs_cached": 0,
        "retried": False,
        "second_pass_pairs": 10,
        "end": "plan_read_back",
    }
    runs = [*([fast] * 9), {**fast, "state": "failed", "stage_ms": {}}]

    report = build_e2e_report(runs, n=10, items=60)

    assert report["verdict"] == "fail" and exit_code(report) == 1
