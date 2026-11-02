# ADR-014: End-to-end performance budget, run limits and determinism

## Status
Accepted (user decision N2, 2026-11-01). **Stage budget measured by SPIKE-1R and SPIKE-2R on 2026-11-01** (spike/findings.md; amendment D77, 2026-11-02). Supersedes ADR-005. Resolves review B1. **Final-gate amendment** D124/D126/D127/D131/D132/D135 (2026-11-02).

## Context
FR-5.5 was revised on 2026-11-01. All limits are configurable:
- **Target**: for 60 items, p95 <= **180 s end to end**, from pressing Calculate/Recalculate to the route on screen, including fetching all uncached road legs.
- **Feasibility limit**: no valid route within **10 min** -> the run aborts with a timeout error.
- **Optimisation limit**: once a valid route exists, optimisation may continue up to **30 min**; at the limit, return the best route, labelled "not fully optimised".
- **Stop**: "Stop and use best so far" is always available.

FR-5.6: identical inputs give identical plans. The OR-Tools routing search is deterministic for an identical model and parameters; only wall-clock cut-offs or a Stop make results timing-dependent.

The earlier claim (ADR-005, feature-delta) that "the plan always returns within 30 s" was false. It budgeted only the solver and ignored the leg fetch, process spawn, guard and persist. It is withdrawn.

## Decision

### 1. End-to-end stage budget (60 items, cold cache, p95 on the Pi)

Status of the rows: **all rows except UI were measured on the Pi** (p95, N=30, cold pipeline, 60-item one-way instance, household services running). The budgets are kept as written; the measured sum is 63.7 s (73.7 s with UI and reserve), leaving ~106 s of slack as margin for larger projects and other hosts. The slack is deliberately **not** spent on a bigger `SOLVER_BUDGET` (user decision D78).

| Stage | Budget | Measured p95 (Pi) | Measured by |
|---|---|---|---|
| Request, snapshot, pre-checks | 1 s | 0.12 s | SPIKE-2R 6f |
| Point snapping (122 points, legal + permissive `locate`) | 5 s | 0.33 s | SPIKE-2R 6b |
| Confirmed matrix, cold (3,660 pairs, 2 calls) | 75 s | 10.48 s | SPIKE-2R K4 |
| Second pass: permissive retries + retrace pairs (<= 700 pairs, see below) | 15 s | 4.04 s (P2 = 720) | SPIKE-2R 6c |
| Reachability check + model build | 1 s | 0.012 s | SPIKE-1R (f2) |
| Solver child spawn + `import ortools` | 3 s | 0.21 s | SPIKE-1R (e) |
| Solve to the deterministic budget | 55 s | 47.56 s (dense I1, worst case) | SPIKE-1R (a, d) |
| Guard + assemble + persist | 3 s | 0.24 s | SPIKE-2R 6f |
| Geometry for the chosen legs (UI-triggered, 2 concurrent) | 12 s | 0.73 s | SPIKE-2R 6d; retrace legs need no call |
| UI polling and render | 2 s | not measured | slice 06a e2e |
| Reserve | 8 s | | |
| **Total** | **180 s** | **63.7 s** (+ UI + reserve = 73.7 s) | |

"Cold" means Valhalla restarted after `drop_caches` (dropping caches under a live process does not evict its mmapped tiles). On NVMe the matrix is CPU-bound: cold adds only ~0.6 s over warm, so prefetching on import is not needed.

**Second-pass bound.** Near endpoints are already resolved in the first pass: they are routed from their snapped road point, giving U2 with legal costing. The second pass therefore contains only:
- (a) pairs that were None after the legal pass, retried with permissive costing;
- (b) retrace pairs entry(t) -> entry(j), only for (t, j) whose direct pair stayed None.

So P2 = N_none + N_retrace <= N_none + T_dead x (n-1). The 15 s row is budgeted for **P2 <= 700 pairs** (about 20% of a 60-item one-way matrix) at <= 22 ms/pair (measured 5.6 ms/pair p95). The adapter groups rows with identical target sets into rectangular sub-matrices, so the requested pairs stay <= 2 x P2 (measured 1.02 x P2). Every run logs `second_pass_pairs`. ~~A run with P2 > 700 is outside the p95 claim and is reported as such.~~ **[Superseded by the final-gate amendment D127 (UD-3): runs with P2 > 700 count toward the p95 claim; their number is reported separately.]**

**Retried runs.** A job in which any Valhalla call was retried (ADR-013 §6) records `retried=true` ~~and is outside the p95 claim~~ **[superseded, D127: it counts toward the p95 claim and is reported separately]**.

A warm Recalculate (all legs cached) is dominated by the solve (<= 55 s) or is instant on a memo hit. If the spikes measure a stage above budget, `SOLVER_BUDGET` is the slack absorber: it is recalibrated so the measured sum of the other stages + solve p95 + reserve <= 180 s, as long as quality stays within 10% of the long reference (SPIKE-1R).

### 2. Limits (configurable, all measured from job start)
- `FEASIBILITY_LIMIT_S = 600`: if no valid route exists at this point, the job aborts with a timeout:
  - during leg fetch: no run, legs kept (ADR-015);
  - during solve: a numbered Failed run with reason "timeout: no valid route within 10 min".
- `OPTIMISATION_LIMIT_S = 1800`: if the deterministic budget is not used up by then, the best incumbent is returned, labelled "not fully optimised (time limit)". Measured from pressing Calculate, i.e. job start (user decision D58).
- **Stop** (`POST /api/plan-jobs/{job_id}/stop`): the best valid incumbent is returned, labelled "not fully optimised (stopped)". If there is none, see ADR-015.

### 3. Deterministic budget as the normal stop
- First-solution strategy `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH`, stopped by OR-Tools **`solution_limit`**, named `SOLVER_BUDGET`, default **10,000** (D78). SPIKE-1R proved it deterministic: 30/30 identical orders per instance, identical on Pi (aarch64 Linux) and Mac (arm64 macOS). It counts every accepted local-search solution, not only improvements. Wall-clock is never the normal stop.
- Pinned `ortools==9.15.6755`; base image `python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`.
- Weighting is **two-phase** (ADR-016 §4): phase 1 limit = `SOLVER_BUDGET / 10`, phase 2 limit = `SOLVER_BUDGET`.
- First-solution strategies that return `ROUTING_FAIL` under forbidden arcs (CHRISTOFIDES, BEST_INSERTION, LOCAL_CHEAPEST_INSERTION, LOCAL_CHEAPEST_COST_INSERTION) are not offered as configuration.
- Solve time per budget is host- and instance-specific (~4.6 ms/solution dense, ~2.0 ms sparse on the Pi); the plans are not. A new host or a much larger project needs time re-calibration only.
- In normal operation the budget ends the search well before any limit, so the run is reproducible (`reproducible=true`).
- Runs ended by the optimisation limit or by Stop are `reproducible=false` and labelled.

### 4. Canonical model (carried over from ADR-005)
Nodes in stable item-id order; integer costs; lexicographic weights (ADR-016) and retrace arcs (ADR-017) derived deterministically from the cache snapshot.

### 5. Fingerprint memo (carried over)
- SHA-256 over: ordered node ids + quantised coordinates + `direction_version`; arc costs including confidence levels and retrace options; objective; provider_id; profile; solver version, strategy and budget. **[Final gate D124 adds: weighting mode (`two_phase` | `lexicographic`), phase-1 and phase-2 solution limits, `RETRACE_PENALTY_M` and `RETRACE_PENALTY_S`.]**
- A stored successful run of the project with the same fingerprint gives its order (`memo_hit=true`, which inherits the source run's `reproducible` flag).
- **Memo reuse of a stopped or time-limited run (review L-5; confirmed by the user, Q-U8 -> D74).** A later Calculate with identical inputs returns the same "not fully optimised" plan, with the label kept. This preserves FR-5.6. There is also a **"Re-optimise (ignore previous result)"** action (`POST /api/projects/{project_id}/plan-runs?ignore_memo=true`) that solves afresh to the budget, creates a new run, and leaves earlier runs untouched.
- Totals, report and warnings are always recomputed.

### 6. Tests
Budget-only with very large limits, so A-6 does not depend on hardware speed. The Stop and limit paths are tested with short configured limits and the Mock's latency injection.

## Alternatives considered
- **Keep a 30 s solver ceiling**: no longer required; FR-5.5 now allows longer solves, and a tight ceiling would cost reproducibility for no user benefit.
- **Wall-clock-only stop (limits as the normal stop)**: fails FR-5.6 for no-change Recalculates.
- **Budget only, no limits**: violates FR-5.5's feasibility/optimisation limits and the Stop action.
- **Eager full matrix prefetch on item import** (to shorten the cold path): would issue routing requests outside Recalculate (A-4 confusion) and waste work on items later excluded. Rejected for the MVP; it can be revisited if K4 fails.

## Consequences
- Positive: the 180 s promise is budgeted honestly across every stage; determinism holds in normal runs; slow or interrupted runs are visible and contained.
- Negative: the solve is now the dominant stage (~48 s of ~64 s measured); the cold matrix risk (SPIKE-2R K4) is retired at 10.5 s. The budget is host-specific and must be re-calibrated if the host changes (README).
- US-06 is rewritten upstream: the end-to-end cold scenario needs Valhalla, so it moves to slice 06; slice 03 keeps the solve-stage scenarios on a precomputed matrix.

## Amendment (final gate, D124, D126, D127, D131, D132, D135) — 2026-11-02
Review findings R-04, R-07, R-13, R-14, R-17 and user decision UD-3 / orchestrator default OD-2. The stage budget and limits above are unchanged.

- **One definition of "60 items" (D131, R-13).** "Items" are the Included **non-anchor** items. The 180 s claim is for k = 60 items **plus Start and End = 62 nodes**, which is exactly what SPIKE-1R/2R measured (40 tracks + 20 POIs). Required one-way pairs: Start -> each item, each item -> End, item -> item: **k² + k = 3,660** for k = 60; Start -> End is needed only when k = 0 (1 pair; OD-4). Round trip (one S/E item): k² + k as well (S/E counts as Start and as End). The earlier "3,423 pairs (k = 58)" reading is withdrawn everywhere.
- **Supported size for the claim (D126, R-07, OD-2).** Up to 60 items (62 nodes) is the supported, measured size. 61–70 items are **allowed** (REQUIREMENTS §4 range) and never refused; the UI shows "Large project - calculation may take longer than 3 minutes" (product-owner wording) and the limits apply as usual. The claim is extended only after slice 03 re-calibrates `SOLVER_BUDGET` and the solve row at 70 items (72 nodes) on the Pi.
- **K5 population (D127, UD-3).** The p95 <= 180 s target counts **every** cold 60-item plan, including jobs with `retried=true`, jobs with P2 > 700 and jobs that waited for the solver slot (ADR-015 amendment D133). Their counts are reported separately for visibility (diagnostics and `kpi-contracts.yaml`), never excluded. The "outside the p95 claim" clauses in §1 and in ADR-013 §6 are superseded; D66/D67 are amended accordingly.
- **Spike figures labelled (D132, R-14).**
  - Point snapping row: the measured 0.33 s is the legal `/locate` at 250 m then 1,500 m. The permissive `/locate` (ADR-016 §1 amendment D79) was not timed; its cost is an **estimate** (about the same again, <= 0.7 s together), well inside the 5 s row. Slice 06a measures it.
  - Second-pass row: P2 = 720 is a **bounding case** (K4 requested all 122 endpoints, far points included). A realistic 60-item instance is about 600 pairs. 700 is the budgeting assumption of the 15 s row (measured 5.6 ms/pair, so the row holds up to about 2,600 pairs), not an exclusion.
- **Fingerprint inputs (D124, R-04).** The memo key also covers the weighting mode, the phase-1 and phase-2 solution limits and both retrace penalties (§5). Test: changing any one of them (and nothing else) gives a memo miss and a fresh solve; changing none gives a hit.
- **Guard at real track sizes (D135, R-17).** The 3 s "Guard + assemble + persist" row was measured with 40 tracks × 2,000 points. Full-sequence hashing (ADR-009 Amendment 2) scales with points, so slice 03 re-measures the row with 40 × 20,000-point tracks on the Pi. If p95 exceeds 3 s, a documented `MAX_TRACK_POINTS` import limit (canonical points per track) is introduced instead of weakening the guard.
- **Solve row and CPU cap.** The 55 s solve row assumes one solver child (ADR-015 D133) on the planner's CPU allocation; with `cpus: 1` (OD-9) slice 03's `perf-pi` re-verifies solve p95 <= 55 s.

## Amendment (DEVOPS re-review, DV-12 / D177) — 2026-11-02
- **K5 gate and reporting.** The authoritative claim gate is `make perf-pi` on cold plans with exactly 60 items (62 stops). Diagnostics additionally report p95 per size band (<=30, 31-59, 60, 61-70). Done, failed and cancelled jobs are all counted (elapsed time as a lower bound) and shown separately; memo hits are shown separately because they are not cold plans. No silent exclusions (UD-3).
