# Overland Route Planner MVP, slice 09: the run on a map, with direction

Date: 2026-11-18. Release `06b8d27` (`06b8d276689ee5c2072dfb81ad9ebb1e4a64dbf9`, image `sha256:86b7e207…`), schema 0010 (no migration), deployed on the Pi on 2026-11-18. Tag `slice-09` on `06b8d27`. Last slice of release R2a "real roads on a map" (D233); the workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

Every plan run now has a map under its itinerary:
- the road legs on their real road shapes from Valhalla;
- each trail in dark green with arrows in the direction it is driven, a green dot at its entry and a red square at its exit;
- the retrace of a dead-end trail in its own style without arrows, labelled "retrace";
- numbered stops, and one "S/E" marker for a round trip;
- grey dashed legs marked "geometry unavailable" when the shapes cannot be fetched;
- the tile credit always shown.

A place can be added by clicking the map ("Click on map", then a name); a click near a trail's entry takes its exact point, so a trailhead can become the Start. The latest run then shows "Stale". The map works on a 390 px phone. Road shapes come from `GET /api/plan-runs/{id}/geometry` (D28, D251-D254); tiles from the settings, and a tile address carrying a key refuses the start.

Stories: US-15 (J-02) and US-16 (J-01). The feature has 14 scenarios: 11 blocking in CI, 3 waiting for slice 08 (a reversed track, the Warnings on the map, the duplicate-POI warning; D256, D262).

## Steps completed (roadmap phase 10, 6 steps)

| Step | Commit | Outcome |
|---|---|---|
| 10-01 | `9762e14` | Road shapes from the road map, kept in memory |
| 10-02 | `ae4a6b3` | The run's road shapes, tracks and markers for the map |
| 10-03 | `ec3d539` | Map tiles from the settings; a keyed tile address refuses the start |
| 10-04 | `8a47b2e` | The run map with direction, markers and stop numbers |
| 10-05 | `1474312` | Add a POI by clicking the map |
| 10-06 | `5ee1624` | Slice 09 blocking in CI; the Stale badge and its refresh (D259) |

All 99 steps of the feature's roadmap so far have complete DES traces.

## Quality gates

| Gate | Result |
|---|---|
| Roadmap review | by the orchestrator against the feature (no separate reviewer pass), recorded as a deviation |
| Adversarial review | 0 blockers, 4 high, 7 medium confirmed by the orchestrator; fixed in `7ec3976` (D261) |
| Rendered-map check (new) | found that MapLibre 6's worker file was missing from the build, so **no line was ever drawn** in the built app, only the markers; fixed in `7ec3976` and now checked in Playwright with MapLibre's rendered features |
| Mutation | `make mutate BASE=slice-06a`: 89.4 %, then **92.7 %** (430 of 464) after the fixes |
| Refactor | no separate pass; the fix pass was the L1-L3 pass (deviation, D261) |
| Suite | 1,165 passed, 122 skipped, 0 failed on the Mac (13 min 11 s) |
| CI | `06b8d27` green; the earlier `c927d91` failed job 2 on the three deferred scenarios, fixed by D262 |

## Pi gate evidence (2026-11-18, orchestrator-run)

| Check | Result |
|---|---|
| Deploy | `06b8d27`; the planner still on Valhalla (`valhalla:3.9.1:1793560782`), health ok |
| Owner's trip (`__demo` copy) | map answer in 0.28 s: 4 road legs on their real shapes (up to 4,503 points), the Assietta track in its driving direction (1,457 points), numbered stops, one S/E marker, entry and exit markers |
| Dead-end retrace | a synthetic demo trail from the Rifugio Scarfiotti road end towards the glacier above the Colle del Sommeiller (no road within 1.5 km of its end): driven in full, then "Retrace Sommeiller dead end (demo)" as its own row, then on from its entry; road 460.5 km, off-road 234.7 km |
| Real browser (headless Chromium from the Mac, the planner on the Pi) | desktop and iPhone 14 width: road, track, retrace lines and arrows render; no horizontal scroll at 390 px; screenshots checked by the orchestrator |
| K5, cold 60 items, 10 runs, ending at the road shapes | **pass**: 119.7-124.0 s (budget 180 s), solve 25.6-27.0 s, no retried run, second pass in all 10 (counted). Report `.data/perf/20261118T015553Z.json` |
| Memory | 11.9 GB available; engine 0.87 GB, planner 0.09 GB |
| Household projects | 7 projects, 37 items, 12 runs: identical to the start of R2a |

## Lessons learned

- **Check what the user sees, not the data behind it.** Every test passed while the built app drew no line: the tests read the API and the HTML markers. One check of MapLibre's rendered features found it.
- **A pending rule must say which slice a scenario waits for.** Enabling slice 09 in CI also ran the three scenarios that wait for slice 08; they now carry both tags and run only when both slices are on.
- **Probe the real world for a demo.** A dead end on real roads needs a trail end with no road near it; one `/locate` call on the live engine found one in a minute.

## Open items carried to later slices

- Cosmetic, for slice 12 (UI foundation): the arrows look large at trip-wide zoom on a phone, and the "retrace" label can sit on a stop number for a short trail.
- From the review (D261): the shape store has no size bound, no single-flight and no negative cache (slice 05); the engine identity is retried per geometry request while the engine hangs; a leg already in flight when another fails still counts as available.
- Three scenarios wait for slice 08 (D256).
- The demo project `__demo Alpi Occidentali giugno 2027 (real roads)` stays on the Pi's planner with three runs; the demo files were removed from the Pi.
- Earlier carry-overs stay open (slices 03b, 06a-ops and 06a archives).

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-09-directional-map.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-09-directional-map.feature`
- Decisions: `feature-delta.md` D251 to D256, D258, D259, D261, D262
- ADRs: ADR-007 Amendment 2, ADR-003 Amendment 2, ADR-004
