# Slice 09: See direction on the map and drop POIs by clicking

Priority: 12 | Stories: US-15 (J-02, Must), US-16 (J-01, Must, B4) | HC-1 (visual) | FR-6.5, FR-3.1 (map click, Phase 1 item 2)

## Goal

Marco opens the map of a plan run and sees tracks with direction arrows and entry/exit markers, road legs in a distinct style, numbered stops and a combined S/E marker. He adds POIs by clicking the map, for example at a trail entry so it can serve as the Start (the D6 workaround).

## IN

- Run map: distinct styles, arrows, entry/exit markers, numbered stops, S/E marker (FR-6.5)
- Add a POI by map click with a name prompt (FR-3.1)
- Usable on a 390 px phone

## OUT

- Geocoding search (Phase 2); offline tiles

## Learning hypothesis

Disproves "arrows plus entry/exit markers make direction unambiguous" if Marco misreads the direction of any of 5 tracks in a blind check.

## Acceptance criteria (each traces to a scenario)

- [ ] US-15: "The map shows which way each trail is driven"; "A round trip shows one combined Start and End marker"; "The map follows a reversed track"; "Giulia uses the map on her phone"; "The map still shows the plan when road shapes are unavailable"; "Compromise legs stand out on the map" (U34)
- [ ] US-16: "Marco adds a trailhead POI by clicking the map"; "A POI at a trail entry can become the Start"; "Cancelling the name prompt adds nothing"; "A POI added on the map marks the plan stale"

## Production-like data

Plan run #4 of "Alpi Occidentali giugno 2027".

## Dogfood moment

Marco does the 5-track blind direction check with Giulia.

## Delivery order (D232, 2026-11-10)

Delivered right after slice 06a, as the last part of release R2a (D233). The scenarios that need slices 08, 06b or 03b ("The map follows a reversed track", "Compromise legs stand out on the map") are deferred and arrive with those slices. Slice 12 (UI foundation) follows.

## Dependencies

Slice 02; slice 08 for "The map follows a reversed track"; slices 06b/03b for "Compromise legs stand out on the map". OD#4 resolved: MapLibre GL JS (DESIGN D19); road shapes via `GET /api/plan-runs/{plan_run_id}/geometry` (DESIGN D28).

## Effort and reference class

1 day, at risk (US-15 0.7 d with S5/S6, US-16 0.3 d).

## Pre-slice spike

None.
