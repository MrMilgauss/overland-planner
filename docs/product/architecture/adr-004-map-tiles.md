# ADR-004: Map tiles — configurable raster source, default OpenTopoMap

## Status
Accepted (user decision, 2026-11-01).

## Context
- The map (US-15, US-16) needs a base layer that helps judge Alpine trails. One household's browsing is very low volume.
- Public tile servers have usage policies: attribution, an identifiable Referer/User-Agent, no bulk download or prefetch, no offline scraping, no SLA.
- Secrets must not reach the browser (NFR-4 spirit). Open-source first; no proprietary service without an explicit request.

## Decision
- The tile source is configured in `.env`: `MAP_TILE_URL` (XYZ template), `MAP_TILE_ATTRIBUTION`, `MAP_TILE_MAX_ZOOM`. It is exposed to the SPA through `GET /api/config/map`.
- Default: **OpenTopoMap** (`https://tile.opentopomap.org/{z}/{x}/{y}.png`, max zoom 17, attribution "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)"). Documented alternative: **OSM Standard** (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`, max zoom 19, "© OpenStreetMap contributors").
- Keys in the path are not detected; use a provider without a key (start-up refuses userinfo, a fragment and key-like query parameters only).
- Policy compliance: attribution is always visible (MapLibre attribution control, cannot be disabled); tiles are only requested on demand by the browser (no prefetch, no server-side cache warming, no offline packs); the browser sends its normal Referer; the default max zoom is no higher than the provider's.

## Alternatives considered
- **Self-hosted Protomaps PMTiles extract (Italy + Alps)**: offline and private, but a vector basemap without contours unless terrain data is added, plus a refresh process. Phase 3 candidate; MapLibre already supports it.
- **OpenFreeMap hosted vector tiles**: no key, generous, but not topographic.
- **MapTiler / Thunderforest (keyed)**: excellent outdoor styles, but proprietary and the key is exposed to the browser. Not chosen without an explicit user request.

## Consequences
- Positive: topographic context for Alpine planning at zero cost; switching source is config only.
- Negative: depends on volunteer-run servers (they can be slow or unavailable); the map is unavailable offline (offline tiles are OUT in slice 09). The itinerary and report do not depend on tiles.
