# Overland Route Planner MVP, slices 03-ops and 03: a full-size trip planned within budget on the Pi, with Stop

Date: 2026-11-10. Release `4e9a727` (`4e9a72781a25111ad111976d5187fc29442327a1`, image `sha256:ff9875cd…`), schema 0008, deployed on pi-host at 2026-11-10T19:21:51Z. Tag `slice-03` to be created at the push. The feature `overland-route-planner-mvp` continues with later slices; this is a slice archive, and the workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

Slice 03-ops (enabler) added the seeded 60-item benchmark fixtures I1/I2 with a committed golden order, a blocking `golden-order` CI job, and `make perf-pi`, which measures the solve stage on the Pi on demand. Slice 03 lets Marco plan a 60-item trip on his Raspberry Pi 5 within the solve budget. The solver child streams its best route so far. Feasibility and optimisation limits count from the job's start. "Stop and use best so far" works while solving and while waiting. A stopped or limited plan carries the label "not fully optimised (time limit / stopped / optimizer failed)". The page shows the run time ("Planned 60 items in ...") and the large-project notice. A no-change Recalculate reuses a stopped plan, and "Re-optimise (ignore previous result)" starts a fresh search. A plan job log, stage timings and a diagnostics page (K2, K3, K5, K7) close D204.

Stories: US-06a (solve stage within budget on the Pi, run time shown) and US-06b (Stop and limits). Job lifecycle per ADR-015. The feature file has 19 scenarios: 17 block in CI, and the 2 `@pi` scenarios run through `make perf-pi`.

## Business context

The slice tests the learning hypothesis "the optimizer is viable on a Raspberry Pi 5 for 60 items" (solve-stage p95 <= 55 s with road km within 10 % of a 30-minute PC search). The hypothesis survives. On the Pi at `cpus: 1`, the 60-item project solved in 47.73-51.37 s over 10 runs (slowest 51.37 s <= 55 s), within 10 % of the 30-minute Mac reference. The golden order is identical on the Mac, amd64 CI and the Pi. The `cpus: 1.5` fallback (D223 c) was not needed. At 70 items the p95 is 69.53 s, which is recorded but not gated (D146). The D135 guard re-measure on 20,000-point tracks missed its 3 s gate (slowest 4.50 s), and the user accepted <= 5 s for such projects (D230).

## Key decisions (feature-delta.md, DELIVER Upstream Issues)

| ID | Decision |
|---|---|
| D222 | GPX Viewer 2 replaces OsmAnd for the manual on-device check; the slice-03 dogfood uses the user's own GPX files from `~/Downloads` (out of git) in a separate demo project |
| D223 | All 13 phase-06 steps go ahead at about 39 h, against the briefs' 1.9 days (03-ops 0.9 d, 03 1.0 d), recorded as missed. The crash label reads "not fully optimised (optimizer failed)". Pi fallback order: `cpus: 1.5`, then a lower `SOLVER_BUDGET`. The 20,000-point guard is re-measured at N=10. Diagnostics and `plan_job_log` land in 03-ops |
| D224 | CI job 8 (mutation) was cancelled at 75 min on `b36e70c` (515 of 2,549 mutants; about 6 h for a full run). Later pushes touched no domain or application file, so job 8 was skipped. CI never completed mutation for 06-06..06-10; the local `make mutate` is the evidence |
| D225 | Scenario #16 (closing the planner leaves nothing running) failed in CI because `ps` without `-ww` cut command lines on the runner. Test-only fixes `8b1e619`, `88aa35b`, `93f1f88` |
| D226 | Tests taking >= 3 s at profile ci get `heavy_property` and move to slow-properties (40 tests, `70cd698`); job 2 went from a timeout to about 9.3 min |
| D227 | A complete valid final always wins, whatever the exit code, Stop or limit; on Stop or limit the parent reads what is already in the pipe first. ADR-015's table of endings to be amended by the architect |
| D228 | The solve child's OR-Tools `time_limit` is the optimisation time left plus 30 s, so no child outlives its own limit (macOS has no PDEATHSIG). Acceptance teardown ends stray children |
| D229 | `plan_job_log.solver_wait_s` is now written (0.0, wait seconds, or null). The K5 "jobs that waited" key is deferred |
| D230 | The 20,000-point guard gate becomes guard_persist slowest of 10 <= 5 s; no `MAX_TRACK_POINTS`, guard unchanged |
| UI-DELIVER-7 | Deviations recorded at review: `#/diagnostics` instead of `/diagnostics`; no K2 home-page banner; leg cache in memory only; `run_time_ms` docstring; 15 tracks in the dogfood; F1 fixed |

## Steps completed (roadmap phase 06, 13 steps, about 39 h planned against the briefs' 1.9 days)

| Step | Commit | Outcome |
|---|---|---|
| 06-01 | `cc06073` | Seeded I1/I2 generator, committed fixtures and golden order |
| 06-02 | `b1a5cbf` | CI job `golden-order` gates publish |
| 06-03 | `c27e638` | Plan job log and stage timings |
| 06-04 | `9c6d96a` | `GET /api/diagnostics` with K2, K3, K5 and K7 |
| 06-05 | `9a1e970` | `make perf-pi` on planner-perf, golden check first, and the 30-minute reference tool |
| 06-06 | `8d621e8` | Solver child streams incumbents; a crash keeps the best route so far |
| 06-07 | `03bf389` | Feasibility and optimisation limits from job start |
| 06-08 | `fb4ef4a` | Stop and use best so far, while solving and while waiting |
| 06-09 | `7f15590` | Look-up latency, legs found so far, and Stop or limit during the road look-up |
| 06-10 | `d1f8034` | Run time, the large-project notice, and reuse of a stopped plan |
| 06-11 | `02c0348` | Browser: Stop button, labels, run time, notice, Re-optimise and diagnostics page |
| 06-12 | `6ea97df` | CI placement of the slice-03 scenarios before they block |
| 06-13 | `7a5b5f6` | Slice 03 blocking in CI |

All 62 steps of the feature's roadmap so far have complete DES traces; `des-verify-integrity` exit 0.

## Quality gates

| Gate | Result |
|---|---|
| Refactor L1-L6 | 10 commits `ad19d8a` .. `399cdb0` |
| Adversarial review | NEEDS_REVISION, one revision pass: F1 Failed-run words on the web (`d1535b9`), F2 `solver_wait_s` (`56827d1`), F3/F6 valid final wins (`5b416ee`), F4 child time limit (`2197cfa`), F5 teardown ends stray children (`7f0befb`); the rest recorded in UI-DELIVER-7 |
| Mutation | Local `make mutate BASE=slice-02`: 96.1 % (1,362/1,418) over 14 domain and application files, 66 min; 56 survivors. The 03-ops run before its push: 97.2 % (738/759) |
| CI fixes | `8b1e619`, `70cd698` (40 tests to slow-properties), `88aa35b` (`ps -ww`), `93f1f88` (process tree in the failure message), registry-test fix `4e9a727` |
| Suite | CI run 42877989739 success and published: job 2 9.3 min, slow-properties 29.1 min, golden-order 1.9 min, job 8 skipped (test-only push) |
| DES integrity | All 62 steps complete |

## Pi gate and demo evidence

Details are in `feature-delta.md`, sections "Slice 03-ops gate on pi-host" and "Slice 03 gate on pi-host"; gate evidence commit `1193919`.

| Check | Result |
|---|---|
| 03-ops `make perf-pi` N=10, 60 items, `cpus: 1` | pass: slowest 50.11 s; within 10 % of the 30-minute reference (1,058.9 road km); deployed `3b34827`, schema 0007 |
| Golden order on the Pi | I1 and I2 pass at both gates; identical on Mac, amd64 CI and the Pi |
| Slice 03 `make perf-pi` N=10, 60 items, `cpus: 1` | pass: solve 47.73-51.37 s, slowest 51.37 s; both `@pi` scenarios pass |
| `make perf-pi POINTS=20000` | fail at 3 s, accepted at 5 s (D230): guard_persist slowest 4.50 s; solve slowest 51.00 s |
| `make perf-pi N=30 ITEMS=70` | report only: p95 69.53 s, slowest 72.97 s |
| Dogfood (D222) | the user's 15 Spanish tracks from Manresa: Stop at 0.8 s gave run #1 "not fully optimised (stopped)", "Planned 15 items in 1.6 s"; an unchanged Recalculate reused run #1 with its label; Re-optimise gave a fully optimised run #3 in 5.3 s, same 3,572.9 km; diagnostics K2 0, K3 0 |
| User's projects | 4 projects identical before and after deploy, perf-pi and dogfood; only the demo project added |
| Memory | planner 110 MiB of 1 GiB after the gate |

## Lessons learned

- **Check the first diagnosis before spending a CI round on it.** #16 was first put down to timing, and the bounded wait in `8b1e619` cost a CI round without fixing it. The real cause was platform-specific `ps` output (procps cuts lines on the runner, macOS does not). The failure message now reports the job and the process tree (D225).
- **A busy-wait in a test can starve the code under test.** The registry tests' `_until` polled with `sleep(0)`, which starved the job threads under mutmut and stopped the first mutation attempt; it now pauses 0.5 ms (`4e9a727`, D226).
- **A job-time projection from Mac timings needs a margin for the runner.** Job 2 was projected at 12.9 min and hit its 20-minute timeout. Slow-properties was projected at 27-32 min and took 34.4 min. On a slow runner the Mac-based projection was about 20-25 % low (D226).
- **Wall-clock tests make CI mutation impractical.** Slice-03 tests wait on real limits, so each timed-out mutant costs about 30 s, and CI job 8 could not finish (D224).

## Open items carried to later slices

- D229: the K5 count of jobs that waited needs a new diagnostics key; deferred.
- UI-DELIVER-7 (1)-(4): ADR-003's SPA-fallback claim and the `#/diagnostics` path; the K2 home-page banner until acknowledged; the leg cache persisted (slice 05); the `run_time_ms` docstring in `run_messages.py`.
- D227: ADR-015's table of endings to be amended by the architect.
- D226: slow-properties took 34.4 min of its 40-minute timeout once; a proposal to restore the margin is owed to the user.
- 56 mutation survivors: about 32 in `plan_job_registry.py`, 9 in `diagnostics_service.py` (the 06-04 gaps), the rest in `plan_request_job.py`, `fingerprint_memo.py`, `run_messages.py` and `plan_run_queries.py`.
- D224: CI never completed mutation for 06-06..06-10 nor for the refactor range; the local run is the only evidence.
- Review F11: the mock latency threads cannot be cancelled.
- Orphaned solve children on macOS: mitigated by the child time limit (D228), not removed.
- D222: the dogfood used 15 tracks, not the 40-trail collection.
- FR-2.4 / D202 / D219: track rows show coordinates, not place names.
- D210: NaN and inf elevations, slice 08.
- No project or run delete: the dogfood project stays on the Pi.

## Links

- Slice briefs: `docs/feature/overland-route-planner-mvp/slices/slice-03-ops-perf-tooling.md`, `docs/feature/overland-route-planner-mvp/slices/slice-03-pi-performance.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-03-pi-performance.feature`
- Decisions, gates and demo evidence: `docs/feature/overland-route-planner-mvp/feature-delta.md`
- ADRs: `docs/product/architecture/adr-014-performance-limits-determinism.md`, `adr-015-plan-job-lifecycle-incumbents-stop.md`
- Perf reports on the Pi: `.data/perf/20261109T203822Z.json`, `20261110T192415Z.json`, `20261110T193651Z.json`, `20261110T195026Z.json`
