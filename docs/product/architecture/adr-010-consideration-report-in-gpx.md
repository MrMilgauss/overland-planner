# ADR-010: Consideration report embedded in GPX 1.1 without extensions

## Status
Accepted (2026-11-01). Settles the "DESIGN picks the mechanism" note of D12 / US-18 S5 / slice 11.

## Context
- FR-6.3 / D12: the GPX export carries the consideration report. FR-9.3 / A-5: standard GPX 1.1, XSD-valid, no proprietary extensions; must open cleanly in OsmAnd, Locus Map and Garmin.
- D10: one waypoint per POI item; a round-trip anchor is one waypoint named "... (S/E)". US-18 S2: 7 waypoints, 10 road legs, 3 tracks in itinerary order. US-18 S6: stale label. US-18 S7: failed runs not exportable.
- Devices tend to re-route `<rte>` elements, which would alter road legs (slice-11 learning hypothesis).

## Decision
Document structure (GPX 1.1 element order is fixed by the schema: metadata, wpt*, rte*, trk*):
- `<metadata>`:
  - `<name>` = "Plan run #N" or "Plan run #N (stale: project changed since this run)";
  - `<desc>` = the plain-text **consideration report**: one line per project item with status Included (positions) / Excluded / Failed (reason), then totals, objective, provider and profile;
  - `<time>` = run time;
  - no `<extensions>`.
- `<wpt>`: one per POI item, in itinerary order, named exactly as the item ("Casa Marco, Torino (S/E)" for a round-trip anchor, per D10 and US-18 S2; no number prefix). `<desc>` = "Stop 1 and 11 - Included" (the stop position goes in `desc`, not in the name).
- `<trk>` per itinerary element, in order: road legs as `<trk>` named "Leg k: A -> B" with one `<trkseg>` of provider geometry; off-road tracks as `<trk>` named exactly as the track item, with the canonical full-resolution points (ele/time kept when present). `<trk><number>` = itinerary stop number; `<trk><type>` = `road` or `offroad`. Both are standard GPX 1.1.
- Road legs use `<trk>`, never `<rte>`, so devices do not re-route them.
- Exporting a Failed run is refused ("This plan run failed"). Exporting while leg geometry cannot be fetched is refused (ADR-007).
- Automated: XSD validation (xmlschema, GPX 1.1 XSD vendored in tests) plus structure assertions. Manual: OsmAnd/Locus/Garmin checks (A-5).

## Alternatives considered
- **Sidecar file (ZIP with GPX + report CSV/JSON)**: richer, but a ZIP does not import directly into OsmAnd/Garmin; FR-9.2 zipped exports are backlog.
- **GPX `<extensions>` with a custom schema**: XSD-valid if namespaced, but it is exactly the "proprietary extensions" FR-9.3 rules out, and devices ignore it.
- **Report as extra waypoints**: pollutes the map with non-places and breaks the "one waypoint per POI item" rule (D10).

## Consequences
- Positive: a single standard file; the report travels with it and is readable in any GPX viewer's description/info panel.
- Negative: some devices (Garmin) truncate or hide long `<desc>` text. The report is complete in the file even where a device does not show it in full.

## Amendment 1 (Revision 1, 2026-11-01)
- **Unconfirmed road legs** (FR-5.8) are named `Leg k: A -> B [UNCONFIRMED - <reason> - check on the ground]`, e.g. `[UNCONFIRMED - ignores access restrictions - check on the ground]` or `[UNCONFIRMED - entry is 1.2 km from the nearest road - check on the ground]` (wording aligned with U33/US-18 and the FR-8.1 style). The `<trk><desc>` carries the full sentence, e.g. "Track 'Strada dell'Assietta' entry is 1.2 km from the nearest road — Unconfirmed, check on the ground". **Export is not blocked** by Unconfirmed legs.
- **Retrace legs** (ADR-017) are a separate `<trk>` named `Leg k: Retrace <track> (B -> A) [UNCONFIRMED - retraces the trail backwards - check it is drivable in reverse]`, `<type>retrace</type>`. The points are the snapshot-version canonical points, reversed. The track item's own `<trk>` keeps the canonical order.
- Off-road track `<trk>` points are read **by the run's snapshot `direction_version`** (ADR-018), so exporting an old or stale run after a Reverse emits the direction it was planned with.
- The report in `<metadata><desc>` adds a line "Unconfirmed legs: N" listing them, and a "Failed" line with the reason (`unreachable` / `timeout`) where relevant. Failed runs remain non-exportable.
- Export is refused only when road geometry cannot be obtained (engine unreachable, or a provider_id mismatch, ADR-007 Amendment 1).

## Amendment 2 (slice 12, D268) — 2026-11-18
- A run planned on the offline road map (provider id `mock:...`, ADR-007) is an estimate: its `<metadata><name>` is "Plan run #N (estimate)" and its file is `<project>-run<N>-estimate.gpx`. Valhalla runs keep "Plan run #N" and `<project>-run<N>.gpx`. With the slice-11 stale label the proposed order is "Plan run #N (estimate) (stale: ...)" (open for DISTILL).
- **As built (step 11-08).** No deviation in the file name or the trip name; the export link in the UI reads "Export GPX of plan run #N" and the older run's export stays under a Failed run (D276, D208). The stale-label order stays as built in slice 11.
