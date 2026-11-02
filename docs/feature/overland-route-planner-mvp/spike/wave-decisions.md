# SPIKE Decisions -- overland-route-planner-mvp

## Assumptions Tested
- **SPIKE-1R**: can OR-Tools on the Pi 5 (`--cpus 2 --memory 1g`) solve the 60-item one-way directional instance (forbidden arcs, lexicographic Unconfirmed weighting, retrace arcs) to solve p95 <= 55 s within 10 % of a 30-min reference, deterministically?
- **SPIKE-2R**: can self-hosted Valhalla on the Pi 5 build Alps tiles under a 9 GB cap and serve the 60-item cold matrix within the ADR-014 budget (p95 <= 75 s) under `mem_limit 4g`, with every confidence-ladder option available?

## Probe Verdict
- **SPIKE-1R WORKS**: `solution_limit = 10000` -> solve p95 47.6 s dense / 21.6 s sparse, road km 0.00 % / 2.57 % (two-phase 0.28 %) off reference; bit-identical orders across repeats and Pi vs Mac; ~60 MB RAM.
- **SPIKE-2R WORKS**: image 3.9.1-arm64 native; build 34 min (at the 9 GiB cap, 0 OOM); cold matrix p95 10.5 s; peak RSS 1.6 GB; all ladder options present; Torino->Susa -0.69 % vs openstreetmap.org.
- End-to-end measured sum ~74 s vs the 180 s FR-5.5 target.

## Promotion Decision
- **DISCARD** (user, 2026-11-02): the findings answer both questions. The walking skeleton is built through the planned slices (01a onward) in DISTILL/DELIVER; promoting now would duplicate slice 01a and skip its DISTILL test design. Probe code deleted (Mac scratchpad and Pi `~/spike-solver`, `~/valhalla-spike/probe`). Kept: `findings.md`, `fixtures/` (routing-port contract suite), `results/` (raw data). Pi keeps extracts, merged PBF, tiles and edited `valhalla.json` (+ `.orig`) under `~/valhalla-spike/`.

## Walking Skeleton
- Not built (DISCARD).

## Design Decisions taken at the gate (2026-11-02)
- **D76** ADR-013 amended: image pinned `ghcr.io/valhalla/valhalla-scripted:3.9.1-arm64@sha256:f182f45e9e71cbe737e6c394d68808c67a7bd12e2a4cc47c4aba864de77ecdc6`; `thor.costmatrix.allow_second_pass=true` mandatory; `max_matrix_distance` 2,000,000; pair limit key is `max_matrix_location_pairs` (F-14 closed); matrix error 170 = bad location, never None; measured RAM/disk.
- **D77** ADR-014 amended: measured p95 per stage recorded; budgets unchanged; ~106 s slack kept as margin.
- **D78** Solver: two-phase weighting is the default, `SOLVER_BUDGET = solution_limit 10000` (phase 1 = budget/10), `ortools==9.15.6755`, base image `python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`. Disjunction feasibility aid (D56) not needed, not built.
- **D79** ADR-016 amended: points classified with legal **and** permissive `/locate`; legal snapped coordinates sent on every call where they exist (prevents footway snapping and matrix-170 failures).
- Patched directly; no extra architect review (user choice). Recorded as U46 in `design/upstream-changes.md`.

## Design Implications
- Slice 06a: ship the `valhalla.json` deltas (incl. `allow_second_pass`), matrix batching `ceil(|targets| / floor(2500 / |sources|))`, error mapping 170/150/171/442, `/status` version pin in the contract suite.
- Slice 06b: dual-costing point snapping; coordinate rule per level; trust matrix None only with `allow_second_pass`.
- Slice 03: two-phase model; exclude CHRISTOFIDES / BEST_INSERTION / LOCAL_CHEAPEST_(COST_)INSERTION from config; planner container `init: true`; keep PDEATHSIG + pipe watchdog.
- `mem_limit`: planner 1g fine (solver ~60 MB); Valhalla 4g (do not go below ~2g).

## Constraints Discovered
- Valhalla tile build sits at the 9 GiB cap: a bigger extract needs 10-11 GB or a PC build (K2 fallback).
- "Cold" needs a Valhalla restart after `drop_caches`; mmapped tiles of a live process are not evicted.
- `country_crossing_cost` is added to returned time -> must stay 0.
- Unknown Valhalla costing options are silently ignored -> pin version via `/status` in contract tests.
- Valhalla RSS stays ~1.3 GB after first use until restart.
- `max_locations` = 20 -> geometry per leg, not one multi-point route.
- Solve seconds are host/instance specific (~4.6 ms/solution dense on the Pi); re-calibrate time for a new host.
