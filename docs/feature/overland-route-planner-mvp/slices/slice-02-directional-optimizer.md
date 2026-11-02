# Slice 02: Direction-safe optimizer with fixed anchors and honest totals

Priority: 3 | Stories: US-03 (J-02), US-04 (J-01), US-05 (J-03) | HC-1, HC-2, HC-5 | A-1, A-2, A-6

## Goal

Marco's multi-track project is ordered by an optimizer that never reverses or cuts a track, always starts at Start and ends at End, refuses to run without both anchors, and gives the same plan for identical inputs. He sees an itinerary table and road/off-road totals.

## IN

- Cost(A->B) = road leg from exit(A) to entry(B); no reverse variant of any track (HC-1, FR-5.2)
- Fixed Start/End, round trips included (HC-2); refusal when an anchor is missing; anchors are POIs only (D6)
- Determinism (FR-5.6): A-6 tests and production use the deterministic search budget; time limits and Stop are safety ends; identical solver inputs reuse the stored order (D15 as amended, D42)
- Itinerary table (FR-6.1); cumulative = road + off-road km up to the end of the stop (D11)
- Totals (FR-6.2); off-road duration = length / 15 km/h by default (FR-4.6)
- Property tests for A-1/HC-1, A-2, HC-5

## OUT

- 60-item performance, limits and Stop (slice 03); exit-side retrace (slice 03b, US-19); objective = time (slice 06a); duration override (slice 07); pinning (Phase 2)
- Revision 6 notes: A-6 runs on the deterministic search budget (D15 amended, U2); a retrace counts as ordinary off-road driving in totals (U32); the property generators gain missing/Unconfirmed pairs and retrace situations in slice 03b (U42)
- Map: in this release (R1) direction is shown in the itinerary text row ("Pian dell'Alpe -> Sestriere"). R1 is internal-only (dogfood by Marco); the map arrives in slice 09.

## Learning hypothesis

Disproves "the directional, fixed-anchor model can be expressed without reverse nodes" if any of 1,000 random cases yields a reversed track, a moved anchor or a non-deterministic plan.

## Acceptance criteria (each traces to a scenario)

- [ ] US-03: "The Assietta is driven from Pian dell'Alpe to Sestriere even when reversing would be shorter" (A-1); "No generated plan ever drives a track in reverse"; "Tracks are always driven in full"; "A loop trail is driven in its recorded order"
- [ ] US-04: "The trip always starts at Start and ends at End" (A-2); "Optimize is refused while an anchor is missing"; "Only POIs can be chosen as Start or End"; "Removing the Start POI clears the Start"
- [ ] US-05: "Identical inputs produce identical plans" (A-6); "Totals separate road and off-road driving"; "The itinerary shows each stop with legs and cumulative distance"; "The off-road speed setting changes track durations"; "Giulia reads the itinerary on her phone"

## Production-like data

Real Assietta, Jafferau loop and Maira-Varaita files; random property cases inside the Alpine box lat 44.0-46.5, lon 6.5-8.5.

## Dogfood moment

Marco loads his 3 favourite trails and checks that the Assietta is never planned Sestriere -> Pian dell'Alpe.

## Dependencies

Slice 01b.

## Effort and reference class

1 day (US-03 0.4 d, US-04 0.3 d, US-05 0.3 d). Reference class: routing model with fixed start/end plus property tests.

## Pre-slice spike (recommended, S4)

`/nw-spike`, 2 h: confirm the chosen solver supports explicit start/end nodes, an asymmetric matrix and a deterministic seed/iteration budget.
