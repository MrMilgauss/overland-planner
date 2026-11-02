# ADR-002: Routing provider — OpenRouteService hosted for the MVP, Valhalla self-hosted in Phase 3

## Status
**Superseded by ADR-013** (user decision N1, 2026-11-01: self-hosted Valhalla is the only MVP routing provider). Kept for history. The OpenRouteService analysis below is still the reference for a possible later hosted adapter.

Previously: Accepted (user decision, 2026-11-01). Resolved REQUIREMENTS Open Decision #1.

Erratum: "12-item reference run -> 90" in the Context below is imprecise. The reference run #4 has 10 Included items (S/E counted once), which gives 10 x 9 = 90 ordered pairs. The precise pair set is defined in ADR-013.

## Context
- Matrix model: sources = item exits, destinations = item entries. 60 items -> 3,600 ordered pairs (3,540 useful); 12-item reference run -> 90. Recalculate fetches only missing pairs (FR-7.2, A-4).
- Needed: asymmetric matrix, per-leg geometry (map, GPX), snap (FR-8.1, Phase 2), profile "car", later avoid-tolls/motorways (Phase 3). Must cross IT/FR/CH/AT borders.
- Host: Pi 5, 16 GB (about 11 GB free), 239 GB NVMe, aarch64. REQUIREMENTS §8 places the self-hosted engine in Phase 3.
- Provider must be swappable by configuration; MockProvider for tests (NFR-8).

## Decision
1. MVP real provider: **OpenRouteService hosted API v2** (`OrsRoutingProvider`), profile `car` -> ORS `driving-car`, API key in `.env` (`ORS_API_KEY`), server-side only.
   - The adapter batches matrix requests to at most 3,500 pairs (sources x destinations) per call.
   - It maps HTTP 401/403 -> `ProviderRejected`, 429 or a quota body -> `ProviderQuotaExceeded`, timeouts/DNS/5xx -> `ProviderUnreachable`.
   - Null cells mean unroutable.
2. **Valhalla** (`ValhallaRoutingProvider`) is designed now (same port, contract below) and delivered in Phase 3 as an optional compose service (profile `valhalla`) with an Italy + Alps tile set built on or for the Pi.
3. `provider_id` = `<engine>:<dataset tag>`, e.g. `ors:v2-public`, `valhalla:alps-2026-10`, `mock:x1.3`. The dataset tag is configured (`ROUTING_DATASET_TAG`) or read from the Valhalla tile build. It is part of the leg cache key, so a tile rebuild or a provider switch never reuses old legs (US-09 S4). The ORS response `graph_date` is recorded per leg for information but is **not** in the key: it changes often and would void the cache and A-4.
4. Port contract (all adapters): `matrix(sources, destinations)`, `route_many(pairs)`, `snap(point)`, `probe()`, `provider_id`, `profile`, `display_name`. Typed errors only; never a partial silent result.

Valhalla adapter contract (Phase 3): `sources_to_targets` with `costing=auto` and costing options for tolls/highways; `max_matrix_distance` raised in the service config to cover a trip (>= 1,500 km); `route` per leg; `locate` for snap; `probe` = `/status` + a 2x2 matrix; dataset tag from the tile build manifest.

## Alternatives considered
| Option | Why not chosen now |
|---|---|
| Valhalla self-hosted for the MVP | No quota and private, but needs a one-off tile build (estimated 3-8 h, 4-8 GB peak RAM on the Pi, unmeasured) and moves a Phase 3 item into Phase 1. Kept as the Phase 3 adapter; the build is timed in the slice-06 spike. |
| OSRM self-hosted | Fastest table, but `osrm-extract` for an approximately 4 GB PBF probably exceeds the Pi's free RAM (preprocessing would have to happen on the PC). Profile changes need a re-extract; arm64 image availability is uncertain. |
| GraphHopper (self-hosted or cloud) | The open-source build has no Matrix API. The cloud free tier (about 500 credits/day) cannot pay for a 60x60 matrix (about 1,800 credits). JVM heap of 3-6 GB. |
| ORS only, no second adapter | Leaves quota, privacy and the Phase 3 avoid-toll consistency gap (the ORS matrix probably ignores avoid options) without a path forward. |

## Consequences
- Positive: slice 06 fits in 1 day; nothing extra runs on the Pi; the cache keeps quota use to about 1-2 matrix calls per Recalculate.
- Negative: needs internet; trail coordinates leave the LAN for ORS; free-tier limits (about 500 matrix/day, about 2,000 directions/day, 40/min, figures to re-check in the spike) cap a fresh 60-item project at 2 matrix calls, and the first geometry fetch is rate-limited (ADR-007).
- Negative: Phase 3 avoid-toll/motorway profiles are likely inconsistent on ORS (directions honour them, the matrix may not). This is resolved by Valhalla.
- External integration: **contract tests recommended for OpenRouteService** (matrix, directions, snap): consumer-driven contracts (pact-python) or recorded fixtures (respx) in CI, plus a scheduled live smoke test.
- Spike before slice 06 (see feature-delta Open questions): ORS limits and error shapes, plus a Valhalla tile-build timing on `pi.example`.
