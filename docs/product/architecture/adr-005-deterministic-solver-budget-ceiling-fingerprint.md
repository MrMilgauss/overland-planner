# ADR-005: Deterministic solver budget + wall-clock ceiling + input fingerprint memo

## Status
**Superseded by ADR-014** (FR-5.5 revised 2026-11-01: 180 s end-to-end target, 10 min feasibility limit, 30 min optimisation limit, Stop action). The 30 s ceiling below no longer applies. The canonical model and the fingerprint memo carry over into ADR-014.

Previously: Accepted (user decision, 2026-11-01). Refined DISCUSS D15.

## Context
- FR-5.5: 60 items within 30 s on the Pi, with a configurable time limit returning the best solution found.
- FR-5.6 / A-6 / US-05 S1: identical inputs give identical plans, including no-change Recalculates in the running product and across restarts.
- D15 (DISCUSS) said the A-6 tests use a deterministic iteration budget and production uses the wall-clock limit. That would leave production no-change Recalculates potentially different, which contradicts US-05 S1 and A9.
- The OR-Tools routing search (single-threaded) is deterministic for an identical model and parameters. The only nondeterminism is where a wall-clock limit cuts it off. Guided Local Search never finishes on its own. There is no seed to fix (confidence medium; confirmed in the slice-02/D14 spike).

## Decision
1. **Canonical model**: nodes ordered by stable item id; anchors at fixed indices; integer arc costs (metres for the distance objective, seconds for time); identical matrices for identical inputs (from the leg cache).
2. **Deterministic budget as the primary stop**: first solution strategy (candidates `PATH_CHEAPEST_ARC`, `LOCAL_CHEAPEST_INSERTION`) + `GUIDED_LOCAL_SEARCH` stopped by a count-based limit (`solution_limit`, or another count limit the spike shows to be deterministic). Configured as `SOLVER_BUDGET` and calibrated on the Pi so a 60-item solve finishes at p95 <= 20 s.
3. **Wall-clock ceiling**: `SOLVER_TIME_LIMIT_S` (default 30). If the ceiling is reached before the budget is used up, the best solution so far is returned, the run is labelled "best found within N s time limit" (US-06 S2) and stored with `ceiling_hit=true`, `reproducible=false`.
4. **Fingerprint memo**: SHA-256 over (ordered node ids + quantised entry/exit coordinates + direction_version, matrix values, objective, provider_id, profile, solver version, strategy, budget). If a stored successful run of the same project has the same fingerprint, its order is reused without solving (`memo_hit=true`), and the run inherits the source run's `reproducible` flag. Totals, durations, report and warnings are always recomputed from the current snapshot (e.g. US-12 S1 duration overrides change totals but not the order).
5. Tests (A-6, property tests) use the budget with a very high ceiling, so results never depend on hardware speed.

## Alternatives considered
- **D15 as written (wall-clock in production, budget only in tests)**: production plans could differ on no-change Recalculates, violating FR-5.6, US-05 S1 and A9.
- **Budget only, no ceiling**: fully deterministic, but on a slower Pi (NFR-1 allows Pi 4) or a larger trip it could exceed 30 s, violating FR-5.5.
- **Memo only (wall-clock in production)**: no-change Recalculates would be identical, but any re-solve of equal inputs on a fresh database (or after the memo is cleared) could differ; budget + memo is stronger.

## Consequences
- Positive: production runs are reproducible except when the ceiling is hit, and even then the memo makes the next no-change Recalculate identical. Unchanged Recalculates are instant (memo).
- Negative: the budget is hardware-sensitive and must be re-calibrated if the host changes (documented in README). A memo hit reports a very small "Optimised in" time; the UI shows "reused identical plan from run #N".
- The D14 spike must confirm which count limit is deterministic, measure time-to-budget on the Pi, and check that quality at the budget is within 10% of a 300 s PC reference.
