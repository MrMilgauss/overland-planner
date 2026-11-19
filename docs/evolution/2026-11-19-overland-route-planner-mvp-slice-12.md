# Overland Route Planner MVP, slice 12: a planner that looks like a product

Date: 2026-11-19. Release `434cf1c` (`434cf1c9628408d297d6b91e928f9e5124ba2b3a`, image `sha256:fe168b68…`), tag `slice-12`, deployed on the Pi on 2026-11-19; then `8a5f95d` (image `sha256:fb3846e8…`, a planner bug fix found at the gate, D279) deployed on top. Schema 0010 (no migration). Delivered before slices 04 and 05 by the owner's decision D263. The workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

The planner now reads as one product on a laptop, a tablet-width window and a 390 px phone:

- the map is the main surface of a project; the Plan, Items and Start and end groups sit beside it (below it on a phone);
- one look on every page (one stylesheet of tokens), light and dark following the system setting, a visible focus ring, 44 px targets;
- one state badge in the Plan group: Loading, Planning (with "Stop and use best so far"), Failed (with the planner's own words), Stale, "Plan run #N", No plan yet;
- a plan on the offline road map carries an "estimate" pill by its provider line and a chip on the map, and its GPX is named `<project>-runN-estimate.gpx` with the trip name "Plan run #N (estimate)"; a plan on real roads carries none;
- under a Failed run the older ready run keeps its itinerary and its export, "Export GPX of plan run #N" (the owner's decision D208, restored by D276);
- the home page warns when a plan run broke one of the planner's hard rules (the K2 banner), until acknowledged in that browser;
- slice 09's cosmetic carry-overs: arrows sized by zoom, and a "retrace" label that keeps clear of the stop numbers.

Stories: US-20 (layout, look, widths), US-21 (states and the estimate marker), US-22 (K2 banner). The feature has 24 scenarios, all blocking in CI: 3 at the HTTP API, 21 in Playwright on chromium and webkit-iphone14.

## Steps completed (roadmap phase 11, 8 steps)

| Step | Commit | Outcome |
|---|---|---|
| 11-01 | `258de5c` | The run detail says `estimate`; the GPX file and trip names say it too |
| 11-02 | `b4f41ba` | One stylesheet of tokens, light and dark, one header, focus ring, 44 px targets |
| 11-03 | `a94b2a5` | Map-first workspace with the Plan, Items and Start and end groups at three widths |
| 11-04 | `18a84c4` | One plan state badge, "Plan run #N", Stop while planning, Failed in the planner's words |
| 11-05 | `734ca27` | The estimate pill and map chip; the older run's export stays under a Failed run; "Click on map" as a map control |
| 11-06 | `47de0d5` | Arrows sized by zoom; a retrace label that avoids stop numbers |
| 11-07 | `92c602e` | The K2 banner on the home page, acknowledged per browser |
| 11-08 | `d2cc48e` | Slice 12 blocking in CI; screenshots for the orchestrator; docs as built |

All 107 steps of the feature's roadmap have complete DES traces (`des-verify-integrity`).

## Quality gates

| Gate | Result |
|---|---|
| Roadmap review | NEEDS_REVISION with 1 blocker, rejected by the orchestrator as wrong; the medium and low findings applied |
| Rendered UI | checked by the orchestrator in real browsers (desktop, tablet width, iPhone 14) on the Mac and on the Pi; it found the full-width "Click on map" bar and the missing gap under the objective, both fixed |
| Refactor L1-L3 | `4b37290` |
| Adversarial review | 4 "blockers" rejected (a half-written file of the parallel refactor), 2 high and 1 medium and 1 low fixed in `f725b52`; a flaky Playwright harness fixed in `434cf1c` (D278) |
| Mutation | `make mutate BASE=slice-09`: **98.1 %** (408 of 416) over the slice's Python files; the gate fix `c7f8ee7` 94.7 %. The web code has no mutation tool in this project |
| Golden order | unchanged throughout (pin and `-m golden_order`) |
| CI | `434cf1c` green (all jobs); `8a5f95d` green after a rerun of job 2, which hit its 20-minute limit once |

## Map-data refresh (first live run, owner-authorised for this session, D277)

| Check | Result |
|---|---|
| `make tiles-refresh`, first run | failed in the build (the network-less build was asked to download the time-zone db); the old map data kept serving, checksums verified |
| Fix and second run | `88ebdd1` carries the serving time-zone db into the build; tileset 20261118 serving, 20261101 kept for rollback |
| `make contract-live` | 1 of 51 failed (the Torino to Susa road shape differs on new map data); switched back to the old map data at once (`make tiles-rollback`), the check fixed to compare a shape by its ends on other map data (`f47d68a`), switched forward: **55 passed** |
| `make acceptance-pi` | first run 2 passed, 1 failed on a missing perf report; after `make perf-pi MODE=e2e`: **3 passed** |
| K5, cold 60 items on the new map data | **pass**: 118.9 to 122.8 s (budget 180 s), solve 26-28 s, no retried run; report `.data/perf/20261118T231448Z.json` |

## Pi gate evidence (2026-11-19, orchestrator-run)

| Check | Result |
|---|---|
| Deploy | `434cf1c` from a clean worktree, exit 0, then tag `slice-12`; `8a5f95d` deployed after it, exit 0 |
| Real browser on the Pi (headless Chromium and WebKit from the Mac) | home, the `__demo` project and Diagnostics at 1440, 768 and 390 px: no sideways scroll; no "estimate" anywhere on the Valhalla runs; road legs on their real shapes on the new map data; Failed badge with the planner's words over "Plan run #4" |
| Memo reuse of a plan with a retrace | found failing (D279, run #5 of the demo project), fixed and redeployed: two reuses in a row both ready with their retrace row |
| K2 | 1 (all time) since the demo run #5: the home page shows the banner until acknowledged in each browser |
| Memory | 12.3 GB available; engine 0.69 GB, planner 0.08 GB |
| Household projects | 7 projects, 37 items, 12 runs: identical before and after (snapshot compared byte for byte) |

## Lessons learned

- **Look at the page, not only the tests.** Every scenario passed while "Click on map" was a full-width bar over the map; a screenshot showed it in a second.
- **A user decision outranks a scenario.** A new scenario said "no Export GPX under a Failed run", against the owner's D208; the step followed the scenario and removed the export. Decisions must be checked when scenarios are written.
- **A gate run is a real use.** Pressing Calculate twice on the demo trip found a guard false positive that no test had: the memo rebuilt its order with the retrace rows.
- **First live runs of ops tools fail in new ways.** The tile build had never run without its spike files; a recorded road shape cannot be expected on new map data.
- **Two agents on one file is a review hazard.** The reviewer read a file the refactor was rewriting and reported four blockers that were not there.

## Open items carried to later slices

- The CI job 2 limit of 20 minutes is close: the same suite took 12 to 20 minutes on different runners.
- "Geometry unavailable" labels pile on each other on a phone for a run planned on older map data (cosmetic).
- From the review: a bare `mock` provider id is worded "Provider: mock" (test harness only); the K2 read is not cancelled on unmount.
- Cold-start check: **passed** by the owner on a laptop (2026-11-19); his feedback (the page follows the engine, not the trip workflow) is D280 and drives the next UI slice.
- Earlier carry-overs stay open (slices 03b, 06a-ops, 06a and 09 archives).

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-12-ui-foundation.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-12-ui-foundation.feature`, `tests/e2e/ui-foundation.spec.ts`
- Decisions: `feature-delta.md` D264 to D279
- ADRs: ADR-003 Amendment 3, ADR-010 Amendment 2
