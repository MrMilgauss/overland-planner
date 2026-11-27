# Slice 12c: The planner knows its map (road-map regions, coverage warnings, place search)

Priority: delivery position right after slice 12b, before slice 04 (owner decisions D295, D298) | Type: user-facing, new behaviour at the edges (a Road map screen with a rebuild workflow, a coverage check, a name search) | Source: the owner's report after slice 12b (D295), the Spain and Occitanie refreshes (D296, D297) and the owner's feedback on the sketches (D299)

Scope note: about 4 days is above the one-day slice rule (D13); the owner chose one slice (D299) and an upper-end assessment is recorded in the DISCUSS block.

## Goal

Marco sees on the page which regions the planner has roads for and how old that map is, is warned as soon as a trail or place falls outside it, and can add a place by typing its name. As owner, he chooses which regions to load or unload on a "Road map" screen and picks when the map is rebuilt; nothing about the map changes unless he chooses it.

## IN

- **A "Road map" screen** (header link beside the projects) where the owner, with no file or script, sees the loaded regions and map date, adds a region by searching the free list of regions by name (for example "Utah") and removes one. Before applying he sees the total download size and an estimated rebuild time (today's eight regions: 6.4 GB, about 55 minutes, 38 of them without planning; total minutes = 8.2 x GB + 2.5, pause = 6 x GB, D305). He chooses "Rebuild now" or a start time (tonight 02:00) and can cancel until it starts. One pending change at a time; at most one rebuild per UTC day; a size limit of 8 GB protects the Pi. "Refresh map data" (same regions, newer data) is the same workflow.
- **Progress and result**: Waiting, "Checking the Pi's disk and memory", Downloading, Building, "Switching to the new map", then done or failed or interrupted. The old map keeps planning during the download; during the build "Plan the route" is disabled with one line. A failed or interrupted rebuild brings the old map back, says why and keeps the change.
- **A small helper installed once on the Pi by the deploy** runs the rebuild; the app only asks it. Nothing changes in the background and nothing starts without the owner's choice and time.
- **The page shows what is loaded, not the pending choice**: the regions of the served map (by their catalogue names) and its map-data date, in view on Build the trip (the date no longer only inside "Details"). Today's served map has no record of its regions, so the page says "Map coverage unknown" until the first rebuild from the app. Regions not linked by land (Europe and Utah) are named as information on the Road map screen and in a warning on Build the trip; never a refusal.
- **Coverage warnings**: a trail or place outside the loaded regions is flagged when it is added (all four ways) and tagged on its row, not only when planning fails. The item is kept (D299, approved screen 1 in D300): a later rebuild may cover it, and planning says why it cannot be reached.
- **Place search by name** as a fourth way in the existing "Add" menu: type a name, press Search, pick a result. A free, keyless service whose terms fit a household planner (OpenStreetMap's Nominatim, D307). The fine print says only the typed words are sent, from the home connection.
- The slice 12 and 12b look, phases, 390 px phone, menus in the page flow (D295, D298) and the user decisions D208, D211, D284, D285 are kept.

## OUT

- Background or automatic refreshes (only the owner's chosen start); drawing the regions on the map; routing across ferries or between areas not linked by land
- Search as you type, searching along a route, search history, a hosted or paid search service, a key of any kind, offline search
- New planning behaviour, day-by-day split, offline tiles, translations

## Learning hypothesis

Disproves "the planner knows its map" if the owner, handed the page cold on a laptop after the gate's one real "Refresh map data" rebuild, cannot (a) add one of his real Spanish GPX tracks and a place found by name, (b) read which regions have roads and the map date without opening "Details", (c) see a warning for a place in Portugal or Morocco, (d) plan the trip, and (e) on the Road map screen add "Utah", read the size and time, schedule the rebuild for a later day and cancel it, in under eight minutes and without help or asking what a word means.

## Acceptance criteria

To be written as scenarios in DISTILL (stories US-27 to US-31 in feature-delta.md). Outcome checks:

- [ ] The owner adds, removes, sizes, schedules and cancels regions on the Road map screen; the page lists the regions of the served map, never a pending choice
- [ ] Size and time are shown before applying; above the limit it is refused; one change at a time, one rebuild per UTC day
- [ ] A failed or interrupted rebuild brings the old map back and says why; planning works during the download and is disabled with a reason during the build
- [ ] Regions and map date are visible on Build the trip without opening "Details"; before the first rebuild from the app the page says "Map coverage unknown" and shows no warnings
- [ ] A trail or place outside the loaded regions is warned at add time and tagged on its row, and is kept
- [ ] A place can be found by name; no result, an unreachable or rate-limited service, and a result outside the map each show a clear message and leave the trip unchanged
- [ ] Only the typed words leave the house, and the screen says so; the service's credit is shown
- [ ] Owner's cold-start check passes

## Production-like data

The owner's real Spanish GPX tracks and "Alpi Occidentali giugno 2027" on the map served on the Pi (eight regions, built on 26 November 2026 without a region record; rebuilt once from the app at the gate); a place in Portugal or Morocco as the outside example.

## Dependencies

Slices 12 and 12b (phases, Add menu, row menu, status words); D296 and D297 (Spain, Occitanie); the map-config endpoint and the refresh script (ADR-013 Amendments 3 and 5), which the Pi helper wraps. The place-search service and the region list are external public services: their terms are checked in DESIGN (done: D306, D307).

## Effort and reference class

About 4 days (3.9 d: US-27 0.8, US-31 0.6, US-30 1.1, US-28 0.8, US-29 0.6), the upper end of one slice by the owner's choice; at risk in the Pi helper, the rebuild workflow, the search service terms and the "outside the map" test (outlines, not rectangles). US-27, US-31 and US-30 are the thin slice if a split is wanted later. The owner's cold-start check is the stop rule.

## Pre-slice spike

None required. DESIGN checked the search service's usage terms and the region outline source (D306, D307).
