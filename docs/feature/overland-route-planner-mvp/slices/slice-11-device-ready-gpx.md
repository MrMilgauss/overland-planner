# Slice 11: Load the whole trip into OsmAnd, Locus and Garmin, and know what to trust

Priority: 14 | Stories: US-18a (J-04), US-18b (J-04) | A-5 | FR-5.8 (GPX marks), FR-6.3 (export part), FR-9.1, FR-9.3 | Revision 6 (U35-U37, D70)

## Goal

Marco exports one GPX 1.1 file of a plan run. It has road legs with real geometry, tracks at original resolution in the direction the run was planned with, and one waypoint per POI item (D10), all in itinerary order, and it carries the consideration report (D12). It imports cleanly into OsmAnd, Locus Map and his Garmin. The file marks Unconfirmed and retrace legs, labels stale runs, and is never produced half-finished.

## IN

- Full-trip GPX 1.1 with no proprietary extensions; checked against the XSD in automated tests
- One waypoint per POI item; a round-trip anchor is ONE waypoint named "Casa Marco, Torino (S/E)" (D10)
- Consideration report in `<metadata><desc>`; each waypoint's `<desc>` gives stop position and status; road legs as `<trk>` (never `<rte>`) (U36; DESIGN D27)
- Unconfirmed and retrace legs marked in their names, e.g. "[UNCONFIRMED - <reason> - check on the ground]"; export not blocked (U35)
- No file when road shapes cannot be fetched (U35)
- Stale runs labelled; Failed runs cannot be exported (A10); past runs keep their planned direction after a later Reverse (U37; DESIGN D47)

## OUT

- Per-item zipped GPX (FR-9.2), CSV/printable (FR-9.4): backlog. Per-day GPX: Phase 2.

## Learning hypothesis

Disproves "one standard GPX is enough for all three device ecosystems" if any of OsmAnd, Locus or Garmin drops tracks, reorders segments, re-routes tracks on import, or hides the UNCONFIRMED marks.

## Acceptance criteria (each traces to a scenario)

- [ ] US-18a: "The exported trip is standard GPX with real road shapes"; "The whole trip opens in OsmAnd in itinerary order" (7 waypoints, 10 road legs, 3 tracks for run #4, A-5); "Tracks keep their original detail and direction"; "Locus Map and Garmin accept the file" (manual); "The exported file carries the consideration report" (all 12 items)
- [ ] US-18b: "A stale plan is exported with a clear label"; "A failed plan cannot be exported"; "Export waits for road shapes"; "Unconfirmed legs and retraces are marked in the file"; "Exporting an older run after a reverse keeps its original direction"

## Production-like data

A branch run on a copy of run #4 of "Alpi Occidentali giugno 2027", computed with Valhalla (rule 3, number not asserted): 10 Included items, 11 stops, 7 POI items. Plus a branch run with an Unconfirmed leg and a Sommeiller retrace.

## Dogfood moment

Marco loads the file on his tablet in the Defender, checks the first three stops, and finds the UNCONFIRMED legs.

## Dependencies

Slice 06a (real geometry), slice 06b and 03b (Unconfirmed/retrace legs), slice 04 (report), slice 08 (Reverse), slice 01b (minimal export).

## Effort and reference class

1 day, at risk (US-18a 0.6 d, US-18b 0.4 d).

## Pre-slice spike

None.
