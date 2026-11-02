# Slice 01b: Walking skeleton (b) - first ordered plan and GPX on the tablet

Priority: 2 | Stories: US-02b | Job: J-01 | Strategy: WS-B (MockProvider)

## Goal

From the slice-01a project, Marco presses Optimize, sees the stops in order with road leg km, and downloads a GPX that opens in OsmAnd. Even this first plan drives the Assietta from its recorded entry to its recorded exit (HC-1 guard).

## IN

- Optimize with the MockProvider (haversine x 1.3); Start first, End last, each other item once
- Ordered stop list with road leg km; each track row shows "entry -> exit"
- HC-1 guard: a one-track plan drives entry -> exit, and the export keeps the stored point order
- Minimal GPX 1.1 export (straight mock legs, track points, one waypoint per POI item)

## OUT

- Multi-track ordering guarantees, totals, determinism (slice 02)
- Toggles, Stale state, consideration report (slice 04); caching (slice 05)
- Map (09); Valhalla (06a); compromise legs (06b, 03b); diff (10); device validation and report in export (11)

## Learning hypothesis

Disproves "the whole browser -> plan -> GPX flow can be completed end to end on the Pi" if Marco cannot go from his slice-01a project to a GPX open in OsmAnd in one session.

## Acceptance criteria (each traces to a scenario)

- [ ] "Marco gets a first ordered itinerary": order Casa Marco -> Strada dell'Assietta -> Briancon -> Casa Marco, with road leg km
- [ ] "Even the first plan drives the trail the way it was recorded": Pian dell'Alpe -> Sestriere in the itinerary and in the exported file
- [ ] "Marco downloads the first plan as GPX": file `alpi-occidentali-giugno-2027-run1.gpx` opens in OsmAnd showing the track and waypoints "Casa Marco, Torino (S/E)" and "Briancon"
- [ ] "A one-way trip ends at its End": the last stop is Aosta

## Production-like data

The slice-01a project with real `assietta.gpx`.

## Dogfood moment

Marco plans an "Assietta day trip from Torino" and opens the GPX on his tablet the same evening.

## Dependencies

Slice 01a.

## Effort and reference class

1 day (US-02b 0.6 d plus integration). Reference class: first solver call + GPX writer.

## Pre-slice spike

None.
