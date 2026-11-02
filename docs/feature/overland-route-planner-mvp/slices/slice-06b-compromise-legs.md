# Slice 06b: Compromise legs are used only when needed, and always explained

Priority: 9 | Stories: US-10b (J-01) | FR-5.8 (Unconfirmed level), FR-8.2 | Revision 6 (U20, U26, D72)

## Goal

When no Confirmed road connects two stops, Marco gets an Unconfirmed compromise leg with its reason, either ignoring access/closure restrictions or using a short off-network link of up to 1,500 m. It is listed under Warnings as "check on the ground". Beyond the link limit there is no connection, and an item with no connection at all fails the run, named.

## IN

- Ladder: Confirmed -> U1 ignore access/closures/restrictions -> U2 off-network link (Confirmed snap 250 m, link <= 1,500 m, configurable) -> None (DESIGN D44, D59, ADR-016)
- Reason per Unconfirmed leg; Warnings entry "check on the ground"
- Cache stores level, reasons and negative results

## OUT

- Retrace (slice 03b); full Warnings list incl. retraces (US-14 S7); map styles (US-15 S6); GPX marks (US-18b S4)

## Learning hypothesis

Disproves "a two-step compromise ladder is enough to plan Marco's real off-network trail ends" if more than 1 of his 10 corpus trails still ends up with no connection after the ladder.

## Acceptance criteria (each traces to a scenario)

- [ ] "A leg that needs a compromise is Unconfirmed and explained"
- [ ] "A trail entry near the road gets a short off-network link"
- [ ] "A place too far from any road gets no link"

## Production-like data

Marco's 10-file corpus on Valhalla; "Rifugio Barbara" (no-access road) and "Lago Nero" (2.1 km off-road) as MockProvider fixtures.

## Dogfood moment

Marco reviews every Unconfirmed reason in his June trip and decides which ones to scout.

## Dependencies

Slice 06a; slice 04 (US-08 preference for fewer Unconfirmed legs, unreachable-item failure).

## Effort and reference class

0.6 day. Reference class: retry ladder over an existing adapter.

## Pre-slice spike

None (covered by SPIKE-2R).
