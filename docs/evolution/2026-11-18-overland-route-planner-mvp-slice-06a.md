# Overland Route Planner MVP, slice 06a: plans on the real road network

Date: 2026-11-18. Release `0c721f1` (`0c721f13af57607f28f1c4b4ed452399f8b7c2f0`, image `sha256:d691fdf0…`), schema 0010, deployed on the Pi on 2026-11-18. Tag `slice-06a` on `0c721f1`. Second slice of release R2a "real roads on a map" (D233); the workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

The planner on the Pi plans on Valhalla, the engine slice 06a-ops put next to it. The switch is one line of the Pi's settings (`ROUTING_PROVIDER=valhalla`), set at this gate. Every run says what it was planned on: "Provider: Valhalla (map data 2026-11-01) / profile: 4x4". Legs are Confirmed (legal by the map data, forest tracks included). Each project minimises road distance (the default) or road time; switching asks no new leg. When the engine cannot be reached, is loading or is another version, Calculate is refused with "Routing engine unreachable - nothing was changed. Try again later." or "Routing engine not ready - nothing was changed. Try again shortly.", nothing changes, and the refusal is counted in the diagnostics. An engine failure during a plan ends it without a run and keeps the legs already found.

Stories: US-10a (J-01) and US-06a S1b. The feature has 11 scenarios (one added at DESIGN, D245), all blocking in CI except the three live ones, which run on the Pi through `make acceptance-pi`; the routing-port contract suite has 9 scenarios for this slice.

## Steps completed (roadmap phase 09, 11 steps)

| Step | Commit | Outcome |
|---|---|---|
| 09-01 | `d44cf9c` | Port with profile, typed errors, off-network places; legs keyed by road map and profile |
| 09-02 | `9e2fe61` | Valhalla adapter reads matrix answers in batches the engine accepts |
| 09-03 | `111bbaa` | Retries, typed errors, the 170 flow, the probe |
| 09-04 | `a6d3710` | Road map chosen by configuration; degraded start when the engine is not ready |
| 09-05 | `e4655cc` | An engine failure ends the job without a run and keeps the answered legs |
| 09-06 | `2fee6ae` | Refusals with clear words while the engine is unreachable or not ready |
| 09-07 | `fd7939d` | Refusals stored; diagnostics count engine refusals (G4) |
| 09-08 | `3462510` | Objective per project, road distance or road time |
| 09-09 | `ea539e4` | Results name the road map, its map-data date and profile |
| 09-10 | `28da3a1` | Browser: provider header, objective choice, engine messages |
| 09-11 | `9e0063b` | Live scenarios for the Pi; slice 06a blocking in CI |

All 93 steps of the feature's roadmap up to here have complete DES traces.

## Quality gates

| Gate | Result |
|---|---|
| Roadmap review | NEEDS_REVISION (2 blockers, 5 high), all applied before any step ran |
| Refactor L1-L3 | `f4ed559` |
| Adversarial review | 1 blocker, 3 high, 6 medium confirmed by the orchestrator and fixed in `0343028` (the most important: `/healthz` waited behind a slow engine probe); three carried over (D257) |
| Mutation | `make mutate BASE=slice-06a-ops`: **95.6 %** (2,185 of 2,285) over 18 files; survivors justified in D257 |
| Golden order | unchanged throughout (pin hashes and weights, `-m golden_order`) |
| CI | `0185a15` and `0c721f1` green; one earlier failure (`0cefbdc`) was a test reading the static home page in a job without a web build, fixed in `0185a15` |

## Pi gate evidence (2026-11-17 and 18, orchestrator-run)

| Check | Result |
|---|---|
| Switch | the Pi's `.env` backed up as `.env.before-06a`, `ROUTING_PROVIDER=valhalla`; health ok, provider `valhalla:3.9.1:1793560782` |
| Owner's trip, real roads | in a separate `__demo Alpi Occidentali giugno 2027 (real roads)` project with the owner's track and places: Casa Marco, Torino -> Aosta 115.0 km -> Briancon 217.9 km -> the Assietta track entry 30.5 km -> 224.8 km off-road -> Torino 45.7 km; road 409.0 km and 5 h 37 min, every leg Confirmed; planned in 2.7 s |
| Engine down | engine stopped: Calculate answered 503 "Routing engine unreachable - nothing was changed. Try again later.", the demo plan unchanged, `g4.engine_refusals_30d` 1; engine started again, healthy |
| K5, cold 60 items, 10 runs (`make perf-pi MODE=e2e`) | **pass**: slowest 119.0 s from pressing Calculate to the stored plan read back (budget 180 s); road look-up about 90 s, solve 25.7-27.8 s; no retried run; all 10 runs asked 1,500 second-pass pairs (counted, not excluded); under D246's 150 s mark, so no batching change. Report `.data/perf/20261117T223126Z.json` |
| Live scenarios (`make acceptance-pi`) | 3 passed: the trip on Valhalla with its header; a trail entry on the Strada dei Cannoni forest track is Confirmed; the 60-item trip within 3 minutes |
| Live engine (`make contract-live`) | 51 passed after one fix: the live matrix answers Torino to Susa with 56,100 m and 3,341 s, the recorded `/route` with 56,099 m and 3,342 s; the check now allows 0.1 % (`0c721f1`) |
| Memory | 12.0 GB available with the engine used (gate 6 GB) |
| Household projects | 7 projects, 37 items, 12 runs: identical before and after |

## Lessons learned

- **A test of "nothing leaks" must read only what holds data.** The password check read the home page, which a CI job serves without a web build; the page holds no run data, so it was never one of the places.
- **Two engine methods, two roundings.** The matrix and the single route of Valhalla differ by a metre and a second on the same path; a check that compares them must say how close is close.
- **A tag push is a CI run too.** It made GitHub's "successful runs of this commit" filter answer nothing, and `make deploy` refused a green commit; the deploy tool now picks the green run itself (`85436e7`, pushed with slice 09).
- **Read the exit code, not the last line.** A deploy failure was hidden by a pipe and the tag went on before the deploy; the planner kept serving the previous release, and the tagged commit was deployed afterwards.

## Open items carried to later slices

- From the review (D257): Stop does not cut an engine call in flight; a place on an isolated road network within 250 m fails with generic words instead of its name (06b); a failed sub-batch above 2,500 targets loses its siblings' answers (latent).
- Places more than 250 m from a legal road fail the plan, naming the item, until slice 06b adds the Unconfirmed levels (D245); the demo track "Maira-Varaita ridge" is one; the owner's projects in Spain are outside the map data.
- The routing engine's identity is cached per process and refreshed by probes; the leg cache is in memory only (slice 05).
- Earlier carry-overs stay open (slice 03b and 06a-ops archives).

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-06a-valhalla-on-the-pi.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-06a-valhalla-on-the-pi.feature`, `tests/contract/routing_port/routing-engine-contract.feature`
- Decisions: `feature-delta.md` D243 to D250, D257
- ADRs: ADR-013 Amendment 4, ADR-011 slice 06a amendment
