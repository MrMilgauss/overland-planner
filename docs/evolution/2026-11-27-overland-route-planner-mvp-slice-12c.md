# Overland Route Planner MVP, slice 12c: the planner knows its map

Date: 2026-11-27. Release `d7249ec` (`d7249ecebf0a592ff3fa31166925e4395ca96156`, image `sha256:36761553…`), tag `slice-12c`, deployed on the Pi on 2026-11-27 (after `2b1ddce` the same day; `d7249ec` is the gate fix D318). Schema 0010 (no migration). Delivered before slice 04 by the owner's decisions D295-D299. The workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

The owner wanted the loaded road-map regions to be visible and changeable from the app, never through a file or a script: "we need a workflow in the UI that allows me to load or unload maps" (D299). Slice 12c, from screen sketches the owner approved before any code (D300):

- a **Road map** screen (header link beside Projects): the loaded regions with sizes and the map date; a search of Geofabrik's free list of regions; add and remove as a pending change; the size, time and pause shown before applying; "Rebuild now" or a start time; Cancel until it starts; "Refresh map data"; progress by step with the minutes left; the result in plain words, a failure keeping the change;
- a **Pi helper** installed by the deploy (one cron line of the deploy user, a non-root container with no network that never mounts the map): it takes the planner's request at its time, validates it strictly, runs the tile refresh on the named regions, retries a busy Pi for 30 minutes, records the result and recovers after a power cut;
- the refresh writes the **record of the map's regions** (`road-map.json` and the borders) and promotes it with the tiles, covered by the integrity check;
- **coverage on Build the trip**: "Roads loaded for …" and the map date; places and trails outside the loaded map tagged and warned once however they were added, kept in the trip; stops in areas not linked by land warned; "Plan the route" disabled with one line while the build stops the engine;
- **place search** as the fourth way to add a place, through the planner to OpenStreetMap's Nominatim (only the typed words, an identifying User-Agent, one request a second, answers remembered, quiet after a busy answer, `PLACE_SEARCH=off` removes it).

Stories US-27 to US-31: 126 scenarios (174 cases), all blocking in CI: 90 pytest scenarios (138 cases) and 36 Playwright tests on chromium and webkit-iphone14.

## Steps completed (roadmap phase 13, 30 steps)

The step table with commits is in `feature-delta.md`, section "Wave: DELIVER / [REF] Slice 12c (2026-11-27)". Backend 13-01..13-14, scripts and deploy 13-15..13-21, web 13-22..13-29, CI and docs 13-30.

## Quality gates

| Gate | Outcome |
|---|---|
| Refactor L1-L6 | 8 commits, behaviour unchanged |
| Adversarial review | two passes on Haiku, 21 findings, 16 fixed, 5 deferred, 1 rejected (D319) |
| Mutation | 96.1 % (1117/1162) since `slice-12b`; 93.3 % on the last fix |
| DES integrity | 144 steps, complete traces |
| CI | green at `d7249ec`; job 2 +88 s |
| Pi gate | one real "Refresh map data" from the app (88 min); household projects byte-identical; screenshots at 1440/768/390, light and dark |

## Lessons

- **Fakes must copy the real service's shape, not only its body.** Geofabrik redirects every `-latest` file; the fakes did not, so all tests passed and the real preview failed (D318).
- **Seams between steps hide bugs that each step's tests cannot see.** A done result without the tileset name (13-21) and a 14 s coverage call (13-22) were found by reading across steps, not by the step's own tests.
- **Run every browser project before pushing.** Two CI failures came from tests run only on chromium.
- **A tight disk shapes the method.** Swap grew past 6 GB during webkit runs; local runs stayed on chromium with traces off, and cache garbage collection (`uv cache prune`, `npm cache verify`) recovered 1 GB.
- **The estimate needs the Pi's numbers.** The build paused planning 61 minutes against 40 estimated (D320).

## Open items carried to later slices

- The owner's cold-start check of slice 12c.
- Whether to recalibrate the D305 estimate from the gate's measurement (D320).
- Deferred review items (D319): two e2e tests fulfil the POST on paper; `valhalla-fetch` hardening; e2e bodies echoing fixture sentences; key and border-name collision by hand-written request; two simultaneous POSTs.
- A switch cut in half (`.routing.env.orig`) is logged, not recovered (D321); the forced-failure rebuild was not run on the Pi.
- The webkit "click has no effect" flake under load is not proven fixed.
- The 8 GB limit is above the measured 6.4 GB build (D314); the gate rebuild (6.7 GB) does not test it.
- The refresh summary says "Adds" all regions when the map's regions were unknown; "Refresh map data" stays clickable during a rebuild (the planner refuses).
- Earlier carry-overs stay open (slices 03b, 06a-ops, 06a, 09, 12 and 12b archives).

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-12c-the-planner-knows-its-map.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-12c-the-planner-knows-its-map.feature`, `tests/e2e/road-map.spec.ts`
- Decisions: `feature-delta.md` D295 to D322
- ADRs: ADR-013 Amendment 5, ADR-019, ADR-020
