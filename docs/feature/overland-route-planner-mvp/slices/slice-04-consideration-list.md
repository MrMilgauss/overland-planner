# Slice 04: The consideration list - nothing silently dropped

Priority: 6 | Stories: US-07a (J-03), US-07b (J-05), US-08 (J-05) | HC-3, HC-4 (stale part) | A-3 | FR-4.1-4.5, FR-6.3, FR-8.2

## Goal

Marco manages one unified item list (filter, Included toggles, bulk toggle, removal with confirmation, anchors locked) and the plan is marked Stale after every change. Every plan run carries a consideration report covering 100% of project items. An item that cannot be placed fails the run, named with its reason.

## IN

- Unified list with a type filter; Included toggle; round-trip anchor shown as one S/E row with no toggle (FR-4.1, FR-4.2)
- Bulk include/exclude; removal with confirmation (FR-4.3, FR-4.5)
- A change marks the plan Stale and enables Recalculate; no automatic run (FR-4.4)
- Consideration report per run: Included + position, Excluded, Failed + reason; frozen at run time (HC-3, FR-6.3)
- A run fails only for an item that cannot be connected at any confidence level in any order, naming it; a single missing pair is routed around; fewer Unconfirmed legs beat a shorter distance; no partial plan is shown (FR-8.2 revised, FR-5.8, A4; U27-U29)

## OUT

- Leg reuse (slice 05); diff (slice 10); report inside the GPX export (slice 11)

## Learning hypothesis

Disproves "one list with toggles is enough for Marco to control a 40-item trip" if he cannot answer "is Via del Sale in this plan?" from the report in under 10 s, or if any random input produces a report that misses an item.

## Acceptance criteria (each traces to a scenario)

- [ ] US-07a: "Excluding a trail marks the plan stale without recalculating"; "Start and End cannot be excluded"; "Marco excludes three tracks at once"; "Marco filters the list to tracks only"; "Cancelling a removal keeps the item"; "Confirming a removal deletes the item and marks the plan stale"
- [ ] US-07b: "Every project item is accounted for in the results" (A-3); "The report is complete for any project"; "A past report keeps the selection it was computed with"; "Home in a round trip is listed once"; "The report states how far a plan was optimised and how many legs are Unconfirmed"; "The report states why a run failed" (U43)
- [ ] US-08: "An unreachable island fails the run and is named"; "Excluding the unreachable item lets the run succeed"; "A failed run never presents a partial plan"; "One missing connection does not fail the plan"; "Confirmed connections are preferred over a shorter compromise"

## Production-like data

The 12-item "Alpi Occidentali giugno 2027" project; Isola del Giglio (42.3600, 10.9010) as the unreachable case (MockProvider fixture; real Valhalla may route it by ferry). The MockProvider is configured per pair (Confirmed / Unconfirmed with reason / none) and per point, plus unreachable points and scripted faults (U30).

## Dogfood moment

Marco drops two trails he is unsure about and reads the report out to Giulia.

## Dependencies

Slice 02.

## Effort and reference class

1 day, at risk (US-07a 0.35 d, US-07b 0.25 d, US-08 0.4 d).

## Pre-slice spike

None.
