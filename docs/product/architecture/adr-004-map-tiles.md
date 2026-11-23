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

## Amendment 1 (slice 12b, D287) — 2026-11-19
- **Two base maps.** The map opens on a calm light base map and a "Terrain" button switches to the raster source above and back (D281). The light map is a vector style: `MAP_BASE_STYLE_URL` (default **OpenFreeMap "Positron"**, `https://tiles.openfreemap.org/styles/positron`) and `MAP_BASE_ATTRIBUTION` (default "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors"; the style carries no credit of its own). `MAP_TILE_URL`, `MAP_TILE_ATTRIBUTION` and `MAP_TILE_MAX_ZOOM` keep their meaning and are now the Terrain map. `GET /api/config/map` gains `base_style_url` and `base_attribution`.
- **Why OpenFreeMap.** No key, no registration, no cookies, no limit on map views or requests, commercial use allowed, MIT-licensed styles, OpenStreetMap data; no SLA and it may stop without notice (as the volunteer raster servers). Only bulk or offline downloads are restricted, which the planner never does (tiles on demand only, as before). CARTO Positron was rejected: it now needs a key. OSM Standard is not a calm map.
- **Guard.** The slice 09 start-up guard (userinfo, fragment, key-like query parameter names, refused by name only) applies to `MAP_BASE_STYLE_URL` too.
- **Failure.** If the style or its tiles do not load, the route, stop numbers and itinerary still show on a plain background; if the Terrain tiles fail, the light map stays visible under them.
- **As built (step 12-07).** Delivered as designed; the light base map settings sit in `bootstrap/settings.py` beside `MAP_TILE_URL` and reuse its key guard. Deviations: the Terrain button uses `rgb()` literals as a map control (no hex, tokens test green), its pressed look was fixed in 12-04 after real tiles showed it unreadable, and the light credit showed twice until 12-04; the browser checks never load real tiles (the 12-07 screenshots test, local only, is the one exception).
