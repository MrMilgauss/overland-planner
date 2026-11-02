# Slice 05: Recalculate without re-fetching what is already known

Priority: 7 | Stories: US-09a (reuse, 0.7 d), US-09b (forget known legs, 0.3 d) - split from US-09 at the final gate (D143) | Job: J-03 | HC-4 | A-4 | FR-7.1, 7.2, 7.4, 7.5

## Goal

Marco presses Recalculate after toggling or adding items. The planner asks the routing provider only for legs it has never computed and shows "computing N new legs / M cached".

## IN

- Reuse of known legs across runs and restarts (FR-7.1, FR-7.2)
- Progress "computing N new legs / M cached" in the UI and in the run log line (FR-7.5)
- Clear the leg cache per project and for all projects (FR-7.4)
- Every Recalculate creates a new plan run (HC-4)

## OUT

- Geocoding cache (Phase 2); diff (slice 10)

## Learning hypothesis

Disproves "reusing legs makes iteration cheap" if excluding one item triggers any routing request, or if adding one POI triggers a request that does not involve that POI.

## Acceptance criteria (each traces to a scenario)

- [ ] "Excluding an item makes zero new routing requests" (A-4a; counted as distinct legs requested at the routing port during Recalculate; locating points, road shapes and health probes do not count; U23, U24)
- [ ] "Adding one POI requests only the legs involving that POI" (A-4b)
- [ ] "A tiny coordinate correction reuses known legs"
- [ ] "Switching routing provider recomputes legs from the new provider"
- [ ] "Known legs survive a restart"
- [ ] "Clearing the leg cache of one project recomputes its legs"
- [ ] "Clearing the leg cache of all projects recomputes every project"

## Technical notes

Cache key = (from rounded to ~5 dp, to rounded to ~5 dp, provider, profile), per FR-7.1. "90 cached" = 10 included nodes x 9 ordered pairs in plan run #4; this is illustrative and the exact count depends on DESIGN's matrix model.

## Production-like data

The 12-item project; a MockProvider that counts requests.

## Dogfood moment

Marco toggles Via del Sale in and out three times and watches "0 new legs".

## Dependencies

Slice 04.

## Effort and reference class

1 day.

## Pre-slice spike

None.
