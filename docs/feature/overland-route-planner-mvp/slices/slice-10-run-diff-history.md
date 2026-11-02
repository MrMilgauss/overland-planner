# Slice 10: See what changed since the last plan run

Priority: 13 | Stories: US-17 | Job: J-03 | HC-4 (diff part) | FR-6.4, FR-6.6 (view only, A2)

## Goal

After Recalculate, Marco sees which items were added or removed, which moved position, and how the totals changed against the previous run. He can browse past runs read-only.

## IN

- Diff against the previous run: added, removed, moved (old -> new position), signed deltas for road/off-road/total km and time, "Unconfirmed legs: before -> after" (U44)
- Run history list (time, objective, totals, status Success / Failed with reason, "not fully optimised" flag, number of Unconfirmed legs) (U44); past runs read-only and immutable

## OUT

- Restoring a past selection (Phase 2); diffs between runs that are not consecutive (backlog)

## Learning hypothesis

Disproves "a diff is what makes iteration decisions easy" if Marco still copies totals into a spreadsheet to compare variants while dogfooding.

## Acceptance criteria (each traces to a scenario)

- [ ] "Marco sees what changed after dropping a trail": Via del Sale removed; Briancon 5 -> 3; road -138.2 km, off-road -38.4 km, total -176.6 km; road time -1h38, off-road -2h34, total -4h12 (S14: off-road 38.4 km / 15 km/h = 2h34; 1h38 + 2h34 = 4h12)
- [ ] "Recalculating without changes shows no changes"
- [ ] "The first run has nothing to compare with"
- [ ] "A past run keeps its original itinerary"
- [ ] "Marco browses the run history" (with status, "not fully optimised" flag and Unconfirmed count, U44)

## Production-like data

Runs #3 and #4 of "Alpi Occidentali giugno 2027" (the road deltas are fixture values).

## Dogfood moment

Marco decides between Via del Sale and Colle del Sommeiller using two diffs.

## Dependencies

Slice 05.

## Effort and reference class

1 day.

## Pre-slice spike

None.
