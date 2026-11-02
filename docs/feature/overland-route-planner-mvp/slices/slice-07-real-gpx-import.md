# Slice 07: Import real, messy GPX collections with trustworthy stats

Priority: 10 | Stories: US-11a (J-02), US-11b (J-02), US-12 (J-01) | FR-2.1-2.5, 2.8, 3.2

## Goal

Marco drops several real GPX files at once. Files with several tracks or segments become separate tracks, which he can merge. Each track shows name, length, entry/exit, elevation and estimated duration, and loops are labelled. He can edit the track and POI details that feed the totals.

## IN

- Multi-file upload; one track per GPX track/segment; original kept; stats; "n/a" when there is no elevation (US-11a)
- Merge segments in file order; loop detection, default 200 m, configurable (US-11b; A6)
- Track fields: name, notes, difficulty, duration override. POI fields: name, notes, category, visit duration (US-12)

## OUT

- KML/KMZ/GeoJSON (Phase 2); broken-data and duplicate warnings (slice 08)

## Learning hypothesis

Disproves "Marco's real GPX collection imports without manual cleanup" if more than 1 of his 10 test files needs editing outside the app before import.

## Acceptance criteria (each traces to a scenario)

- [ ] US-11a: "Several files are imported at once with their stats"; "A file with two segments becomes two tracks"; "The original file is kept unmodified"; "A file without elevation still imports"; "Entry and exit are the first and last recorded points"
- [ ] US-11b: "Two segments of one trail are merged"; "Merged segments follow the order of the file"; "A loop trail is labelled and keeps its direction"; "A stricter loop distance changes the label"
- [ ] US-12: "A duration override replaces the estimate in the totals"; "A POI visit duration counts in the trip time"; "Editing details needs no new road legs"; "Marco records difficulty and notes for a trail"; "Marco categorises a POI"

## Production-like data

Marco's 10 real files: assietta, jafferau-loop, maira-varaita (no elevation), via-del-sale (2 segments), sommeiller, lombarda and others.

## Dogfood moment

Marco imports his whole "Alpi 2027" download folder in one drag.

## Dependencies

Slice 02 (totals); slice 05 (for "no new road legs").

## Effort and reference class

1 day (US-11a 0.4 d, US-11b 0.3 d, US-12 0.3 d).

## Pre-slice spike

None.
