# Slice 08: Fix backwards and broken input data before it reaches the plan

Priority: 11 | Stories: US-13 (J-02), US-14 (J-02) | HC-1 (explicit reverse) | FR-2.6, FR-2.7, FR-6.7, FR-8.3

## Goal

Marco reverses a track he knows was recorded backwards, using an explicit action that asks for confirmation and is logged in the project history. On import he is warned about broken data (a single point, huge jumps) and duplicates. The Results show a Warnings section listing unresolved import warnings for the run (D12).

## IN

- "Reverse track direction": dialog stating FROM/TO, history entry with time, canonical direction updated, original file untouched, plan Stale (US-13)
- Warnings for a single-point track, a jump above a configurable threshold (default 5 km, checked for 0 false positives on the 10-file corpus; A8 amended, U40), an identical file, or POIs within 50 m. Warnings never block an import. A track with a jump keeps the jump in its length; the warning says so (S1).
- Results "Warnings" section: unresolved import warnings of the run's Included items (FR-6.7)

## OUT

- Overlap warnings (FR-8.4, backlog); undo other than reversing again; snap distance (Phase 2)

## Learning hypothesis

Disproves "an explicit reverse action is enough to handle backwards recordings safely" if Marco, while dogfooding, reverses a track without knowing which way it will now be driven.

## Acceptance criteria (each traces to a scenario)

- [ ] US-13: "Marco fixes a descent recorded uphill"; "Cancelling the reverse dialog changes nothing"; "Reversing a loop flips its driving direction"; "Nothing but the explicit action changes a track's direction"
- [ ] US-14: "A huge jump between points is flagged on import"; "A track with a single point is flagged"; "The same file imported twice is flagged as a duplicate"; "POIs close to an existing POI are flagged" (30 m shown / 80 m not); "The results list unresolved import warnings for the run"; "A resolved warning disappears from the next run"; "The results list Unconfirmed legs under Warnings" (U33; depends on slices 06b and 03b)

## Production-like data

Marco's own OsmAnd recording `jafferau-descent.gpx` (recorded uphill); a real GPS-glitch file `lombarda-glitch.gpx`; `sommeiller-stub.gpx` (1 point). Each Jafferau file is used in its own scenarios (S1).

## Dependencies

Slice 07 (import), slice 04 (Stale).

## Effort and reference class

1 day (US-13 0.5 d, US-14 0.5 d).

## Pre-slice spike

None.
