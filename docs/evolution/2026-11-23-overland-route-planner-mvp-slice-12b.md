# Overland Route Planner MVP, slice 12b: the planner follows the trip

Date: 2026-11-23. Release `5e63540` (`5e635402c28474e89acc12c49e09ac6e1e20de20`, image `sha256:0a91dcb1…`), tag `slice-12b`, deployed on the Pi on 2026-11-23; then `9fd0c15` (image `sha256:eaf1715d…`, two display fixes found at the Pi gate, D294) deployed on top. Schema 0010 (no migration). Delivered before slice 04 by the owner's decision D281. The workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

The owner passed the slice 12 cold-start check but called the page "messy" and "chaotic": it followed the engine, not the trip (D280). Slice 12b rebuilds the project page around the trip workflow, from screen sketches the owner approved before any code (D282):

- three phases, one main action each: **Build the trip** (one list of stops and trails, one "Add" for GPX upload, a click on the map or typed coordinates, Start and End set from a place's row, a small "Plan for" switch; "Plan the route"), **Planning** (progress, the planner's step words, "Stop and use best so far"; the trip read-only, no export), **Your route** (a summary card with totals, road against off-road, "Real roads" or "Estimate", "Export GPX" and "Edit trip", then the itinerary as numbered steps);
- the itinerary and the map linked both ways: a step selected zooms the map and dims the other lines, a stop pressed on the map highlights and scrolls to its step, "Show whole route" returns;
- status in user words: Loading, "Planning…", "Route ready", "Couldn't plan" (with the planner's own words), "Out of date, plan again", "No plan yet"; under "Couldn't plan" the earlier route stays as "Previous route" with its export (D208 as the owner reworded it in D282);
- engine details (run number, provider and map date, timings, the planner's run lines, "Re-optimise") behind one closed "Details" (D285);
- a calm light base map (OpenFreeMap "Positron": no key, no usage limit, OpenStreetMap credit) with a "Terrain" button to the topographic map, remembered per browser; route lines thicker, on a white outline, always above the map's labels (D287);
- the map shows the trip's places and trail ends before any plan, so "Click on map to add" works on a new project (D288);
- one column below 1024 px with the main action pinned at the bottom (D289). Slice 12's look, states, estimate marker, K2 banner and the D208 export rule are kept.

Stories: US-23 (phases), US-24 (card and linked itinerary), US-25 (status and Details), US-26 (calm map). The slice has 29 scenarios (35 cases), all blocking in CI: 2 at the HTTP API and start-up, 27 in Playwright on chromium and webkit-iphone14. The slice 12 checks 12b replaced were changed on purpose and listed (D290).

## Steps completed (roadmap phase 12, 7 steps)

| Step | Commit | Outcome |
|---|---|---|
| 12-01 | `d7cdf62` | The planner names the light base map and its credit; a keyed base map address refuses the start |
| 12-02 | `eec188b` | A calm base map with Terrain; the route outlined and always on top |
| 12-03 | `281bc57` | Three phases, status in user words, the Planning phase, a first route card |
| 12-04 | `25e67eb` | One trip list and one Add; the map shows the trip before a plan; two map defects fixed |
| 12-05 | `5b436eb` | Engine details behind one closed Details; Couldn't plan, Out of date, stopped plan, notices |
| 12-06 | `7ae0ee2` | The route card's numbers and an itinerary linked both ways to the map |
| 12-07 | `d8c1157` | Slice 12b blocking in CI; phase screenshots; docs as built |

All 114 steps of the feature's roadmap have complete DES traces (`des-verify-integrity`).

## Quality gates

| Gate | Result |
|---|---|
| Screen sketches | approved by the owner before any code (D282) |
| Roadmap review | NEEDS_REVISION (Haiku): the D208 label finding resolved by the owner-approved sketch wording; the "Plan for" switch, two D290 rows and renamed files applied |
| Rendered UI | checked by the orchestrator on real tiles (Mac and Pi; 1440, 768, 390 px; light and dark; both base maps): found an unreadable pressed Terrain button, a doubled credit, a plain-text Details summary, map tags cut at the edge, "Show whole route" under the credit on a phone and a near-invisible credit in dark mode, all fixed |
| Refactor L1-L3 | `70a99ba` (with the gate fixes `63c4e41`) |
| Adversarial review | NEEDS_REVISION (Haiku), every claim checked: 1 high (the map offered "Click on map to add" while planning), 2 medium (a Build flash on open; a bare key-like word echoed in a start-up refusal, inherited from slice 09) and 6 low fixed in `5da424e`, `83d2fcf` |
| Mutation | `make mutate BASE=slice-12`: **94.7 %** (36 of 38, the D279 fix). Slice 12b's own Python (bootstrap settings, HTTP schema) is outside the project's mutation scope (domain and application only) and the web code has no mutation tool; the settings guard is covered by Hypothesis properties |
| Golden order | unchanged throughout (pin 5, golden_order 2) |
| CI | `90d14e7` failed job 2 once (slice 02's phone check still asked for the objective line in view; fixed in `5e63540`); `5e63540` and `9fd0c15` green, all jobs |

## Pi gate evidence (2026-11-23, orchestrator-run, D294)

| Check | Result |
|---|---|
| Deploy | `5e63540` from a clean worktree, exit 0, then tag `slice-12b`; `9fd0c15` deployed after it, exit 0 |
| Real browser on the Pi | `__demo Alpi Occidentali giugno 2027 (real roads)` at 1440 px (light, dark, Terrain), 768 px and 390 px (Chromium at the iPhone 14 viewport; the Mac's WebKit could not reach the Pi on the local network this time): route readable on both base maps; phases, card, linked itinerary and Details work; no sideways scroll |
| A fresh plan | Edit trip, then Plan the route: "Route ready" on real roads, the dead-end retrace listed once |
| K2 | 1 (all time, unchanged since slice 12) |
| Memory | 11 GB available; engine 0.69 GB, planner 0.09 GB |
| Household projects | 7 projects, 37 items, 12 runs: identical byte for byte before and after both deploys |

## Lessons learned

- **Show the screen before the code.** The approved sketches settled most design questions (phases, wording, the previous route's label) and one reviewer "blocker" was answered by quoting them.
- **Real tiles find what test tiles hide.** Every map defect of the slice (unreadable pressed button, doubled credit, overlapping controls, dark-mode credit) passed against the tests' blank tiles and showed at once on real ones.
- **Full-page screenshots lie about sticky elements.** A pinned action bar looked as if it covered the list; real-viewport shots showed it did not.
- **Tests driven from another runner escape local checks.** Slice 02's phone check runs Playwright from pytest; no step ran it locally, and CI caught it.
- **Usage limits interrupt crafters.** Step 12-06 stopped twice on rate limits; resuming the same agent kept its work.

## Open items carried to later slices

- The owner's cold-start check of slice 12b (the learning hypothesis) is pending.
- Track shapes are not drawn before a plan (only their ends): the item list has no geometry (D288, reported, not added).
- The style address guard checks query names only; keys in a path or inside the fetched style are not detected (as for tiles).
- WebKit from the Mac could not reach the Pi on the local network in this session (Chromium could).
- Earlier carry-overs stay open (slices 03b, 06a-ops, 06a, 09 and 12 archives).

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-12b-trip-workflow.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-12b-trip-workflow.feature`, `tests/e2e/trip-workflow.spec.ts`
- Decisions: `feature-delta.md` D282 to D294
- ADRs: ADR-003 Amendment 4, ADR-004 Amendment 1
