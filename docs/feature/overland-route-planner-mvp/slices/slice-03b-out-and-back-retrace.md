# Slice 03b: A dead-end trail is driven and then retraced, never reversed

Priority: 5 | Stories: US-19 (J-02) | HC-1 (exit-side retrace), FR-5.8, FR-5.3 (amended), A-7 | New in Revision 6 (U31, D69)

## Goal

When no road leaves a trail's exit but one leaves its entry towards the next stop, Marco's plan drives the trail in full, then retraces it exit -> entry as a separate Unconfirmed leg, and continues from the entry. The planner never enters a trail from its exit.

## IN

- Retrace as a last-resort Unconfirmed leg: "Unconfirmed: retraces the trail backwards; check it is drivable in reverse" (HC-1, FR-5.8)
- Retrace only when no road leg at any level leaves the exit; the mirror case is never proposed; such a track is Failed "unreachable"
- The retrace is its own itinerary leg; its km and time count as ordinary off-road driving with no separate breakdown (FR-5.3 amended, DESIGN D57)
- Property tests over sparse random projects (U42)
- MockProvider per-pair configuration (Confirmed / Unconfirmed / none), extended in slice 04

## OUT

- Retrace in Warnings (US-14 S7, slice 08), on the map (US-15 S6, slice 09), in the GPX (US-18b S4, slice 11)
- Access-ignoring and off-network-link compromises (slice 06b)

## Learning hypothesis

Disproves "the exit-side retrace can be added without ever producing a reversed track item" if any of 1,000 sparse random cases drives a track item exit -> entry, or plans a retrace while a road leaves the exit.

## Acceptance criteria (each traces to a scenario)

- [ ] "A dead-end trail is driven in full and then retraced" (A-7)
- [ ] "A trail is never entered from its exit"
- [ ] "No retrace when a road leaves the exit"
- [ ] "A retrace is its own leg and counts as off-road driving"
- [ ] "No track item is ever driven backwards, retraces included" (property)

## Production-like data

Real dead-end pass: track "Colle del Sommeiller" (Rochemolles -> Colle del Sommeiller, 12.4 km fixture); "no road onward" and "Valle Stretta" are MockProvider fixtures.

## Dogfood moment

Marco adds the Sommeiller to his project and checks that the plan goes up, comes back down, and never starts from the top.

## Dependencies

Slice 02 (model, properties), slice 03 (search budget). The Failed report row for S2 is shown once slice 04 lands; until then the run's failure message names the track.

## Effort and reference class

0.8-1 day. Reference class: adding a conditional derived leg to a routing model plus property generators (DESIGN ADR-017).

## Pre-slice spike

None. SPIKE-1R's sparse instance already exercises missing exit-side pairs.
