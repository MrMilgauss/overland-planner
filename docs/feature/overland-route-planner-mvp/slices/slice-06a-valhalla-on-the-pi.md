# Slice 06a: Plan on the real road network with Valhalla on the Pi

Priority: 8 | Stories: US-10a (J-01), plus US-06a S1b | Phase 1 item 4 (revised), FR-5.1, FR-5.5, FR-5.8 (Confirmed), NFR-4, NFR-6 | D7 | Revision 6 (U26, D72)

## Goal

Valhalla runs in Marco's compose stack on the Pi. Switching from the MockProvider is a configuration change. Marco sees real road km and hours, with legs on legal roads, forest tracks included, marked Confirmed. A cold 60-item plan reaches the screen within 180 s (p95). The engine being down or still loading gives a clear message that changes nothing.

## IN

- The planner's Valhalla adapter, selected by configuration; no API key (DESIGN D40, ADR-013); routing-port contract suite on recorded fixtures (US-10a `@technical`). The Valhalla service, tileset seeding, build profile, `contract-live`, `acceptance-pi` and the end-to-end `perf-pi` mode moved to slice 06a-ops (D145)
- Results header "Provider: Valhalla (map data <date>) / profile: 4x4"
- Confirmed legs (level 1 of FR-5.8)
- Objective per project; new projects default to distance (D7)
- "Routing engine unreachable" / "Routing engine not ready" -> no run, nothing changed; resolved legs kept in the shared cache
- End-to-end budget check: US-06a S1b

## OUT

- Unconfirmed ladder (slice 06b); retrace (slice 03b)
- Hosted adapter, e.g. OpenRouteService (Phase 3 or last-resort fallback); avoid-motorway/toll profiles (Phase 3)

## Learning hypothesis

Disproves "self-hosted Valhalla on the Pi serves a 60-item cold matrix within the 180 s budget" if SPIKE-2R K4 fails, or if US-06a S1b's p95 exceeds 180 s.

## Acceptance criteria (each traces to a scenario)

- [ ] US-10a: "Marco plans with Valhalla on his Pi" (Torino -> Susa within 15% of openstreetmap.org's Valhalla planner); "Marco switches the objective to road time"; "New projects minimise road distance by default"; "Routing engine unreachable leaves the project intact"; "The routing engine is still loading its map data"; "Marco's password is never shown"; "A trail entry reached by a forest track is Confirmed"
- [ ] US-06a: "A 60-item trip with no known roads is on screen within 3 minutes" (slowest of 10 <= 180 s; every cold run counts, retried jobs and second-pass > 700 pairs included and reported separately, D147, D159)

## Production-like data

Valhalla tiles for the Western Alps (IT/FR/CH) on the Pi; the 12-item project and the 60-item fixture.

## Dogfood moment

Marco compares mock and Valhalla road km for his Assietta weekend.

## Dependencies

Slice 05 (legs reused per provider; a map-data rebuild counts as a provider change) and slice 06a-ops (Valhalla serving on the Pi). OD#1 resolved: self-hosted Valhalla (DESIGN D40).

## Effort and reference class

1 day, at risk (re-estimated at the final gate, D145: adapter + contract suite on fixtures 0.6 d, US-10a user-facing parts 0.3 d, S1b measurement 0.1 d). SPIKE-2R is done. Reference class: HTTP adapter + error mapping.

## Pre-slice SPIKE-2R - MANDATORY GATE (U13, U26)

`/nw-spike` on Marco's Pi 5: build or load Valhalla tiles and time a cold 60-item matrix.
Kill criteria (DESIGN, incl. K4): the tile build is not feasible on the Pi, or the cold matrix cannot fit the 180 s end-to-end budget. Fallbacks in order: PC-built tiles, then a hosted adapter (user decision). Also verify the real-world fixtures: forest-track access for "Maira-Varaita ridge" (US-10a S7) and the optional "Vetta del Monte Bianco" unreachable case (US-08).
