# Slice 12b: The planner follows the trip, not the engine (trip workflow)

Priority: delivery position right after slice 12, before slice 04 (D281, owner decision 2026-11-19) | Type: user-facing redesign of existing screens, no new planning behaviour | Source: the owner's feedback after the slice 12 cold-start check (D280)

## Goal

Marco opens a project and the page walks him through his trip in three phases: he builds the trip, waits while it is planned, and sees his route as the main result, which he can export or change and plan again. Each phase shows what matters in it first and hides engine details.

## IN

- Three phases with one main action each:
  - **Build the trip**: one list of the trip's stops and trails (today's Items), one "Add" control (upload GPX, click on the map, or type coordinates), Start and End set on a stop in the list, and the objective as a small setting. Main action: "Plan the route".
  - **Planning**: progress and "Stop and use best so far"; the inputs are read-only meanwhile.
  - **Your route**: a summary card at the top (total distance and time, road vs off-road, "Real roads" or "Estimate"), then the itinerary as a numbered timeline linked to the map (a step selected zooms the map to it, a map stop selected highlights its step). Main action: "Export GPX"; "Edit trip" goes back to the first phase.
- Status in user words: "Route ready", "Planning…", "Couldn't plan" (with the planner's own message), "Out of date, plan again" (today's Stale). An estimate route says "Estimate" in the card and on the map.
- Engine details behind one closed "Details" disclosure: the run number, the provider and map-data date, the timings, "Reused the identical plan of run #N", and "Re-optimise (ignore previous result)".
- A readable map: a light, low-contrast base map by default with a "Terrain" toggle for today's topographic map (both credited, no key, terms fit a household planner, ADR-004); thicker route lines with a light outline, drawn above the base map's labels, colours that keep road, trail and retrace apart.
- 390 px phone, tablet width and laptop, as slice 12; the slice 12 visual system, states, estimate marker, K2 banner and the D208 export rule are kept.

## OUT

- New planning behaviour, new data or new server endpoints (the run detail already has what the card needs; anything missing is reported, not added)
- Day-by-day splitting of the itinerary, editing the order by hand, offline tiles, a custom map style of our own, branding, translations

## Learning hypothesis

Disproves "the page now follows the trip workflow" if the owner, handed the page cold on a laptop, cannot (a) build a trip with one GPX and two places, (b) plan it, and (c) read where the trip goes next from the result, without asking what any element means, in under three minutes; or still calls the page chaotic.

## Acceptance criteria

To be written as scenarios in DISTILL (stories US-23 to US-26 in feature-delta.md). Outcome checks:

- [ ] Each phase shows one main action, and only the elements of that phase are open
- [ ] No run number, provider id, timing or memo text is visible outside "Details", except inside the planner's own words (a failure message names its run, D211)
- [ ] Under a "Couldn't plan", the previous ready route keeps its itinerary and its "Export GPX", and the page says it is the previous route (D208); an "Out of date" route stays exportable (A-10)
- [ ] The summary card and the first itinerary steps are in view without scrolling on a laptop
- [ ] Selecting an itinerary step moves the map to it, and the reverse
- [ ] The route lines stay readable on both base maps (contrast against the base map checked)
- [ ] Owner's cold-start check passes and the owner no longer calls the page chaotic

## Production-like data

The owner's "Alpi Occidentali giugno 2027" and its `__demo` copy on real roads (map data 2026-11-18).

## Dependencies

Slice 12 (visual system, states, estimate marker). Existing Svelte 5 and MapLibre stack; the second base map is a tile source in the settings (ADR-004), not new technology.

## Effort and reference class

About 1.5 to 2 days, at risk: a redesign of every control of the workspace. The owner's cold-start check is the stop rule.

## Pre-slice spike

None. DESIGN starts with screen sketches per phase and width, shown to the owner before code.
