# ADR-013: Routing provider — self-hosted Valhalla on the Pi is the only MVP provider

## Status
Accepted (user decision N1, 2026-11-01). **Parameters validated by SPIKE-2R on 2026-11-01** (spike/findings.md; amendment D76, 2026-11-02). Supersedes ADR-002. Resolves REQUIREMENTS Open Decision #1 ("#1 resolved: self-hosted Valhalla in the MVP; a hosted adapter may come later"; §8 Phase 1 item 4).

## Context
- The user wants no API key, no quota and no coordinates leaving the LAN.
- The Pi 5 has 16 GB RAM (about 11 GB free next to existing workloads using 4.1 GB), 4 cores, 239 GB NVMe free.
- Trips cover Italy and the Alps across IT/FR/CH/AT borders.
- FR-5.8 adds road-leg confidence levels. Tracks often start or end off paved roads, so forest tracks must be routable, and permissive retries plus off-network links are needed (ADR-016).
- FR-5.5 (revised) target: p95 <= 180 s end to end for 60 items, **including the cold leg fetch** (ADR-014).
- Required pair set, defined precisely. Let n be the Included items, with a round-trip S/E counted once.
  - Round trip: all ordered pairs exit(i) -> entry(j) with i != j, so n(n-1). Run #4 has 10 items, so 90 pairs.
  - One-way, with k = n - 2 non-anchors: Start -> k, k -> End, k -> k, plus Start -> End, which gives k^2 + k + 1. The US-06 fixture (60 items, one-way) needs 3,423 pairs if its 60 items include Start and End (k = 58). The spikes measured the larger reading, 60 non-anchor items plus Start and End (k = 60): k(k-1) + 2k = **3,660 pairs**, plus Start -> End. All measured budgets therefore hold for the 3,423 case too.
  - Plus entry(t) -> entry(j) pairs, fetched only for retrace candidates (ADR-017).

## Decision
1. **Valhalla** (MIT; tiles from OSM, ODbL) runs as a service in the **same compose stack**. Image **`ghcr.io/valhalla/valhalla-scripted:3.9.1-arm64@sha256:f182f45e9e71cbe737e6c394d68808c67a7bd12e2a4cc47c4aba864de77ecdc6`** (Valhalla 3.9.1; native arm64 confirmed by SPIKE-2R K1).
   - Tiles live on their own volume `valhalla-data` (`/custom_files`).
   - Day to day, the service only serves tiles. Building them is a separate one-shot compose service, `valhalla-build` (profile `valhalla-build`). It is run manually: first install, then a quarterly refresh.
   - Extract: Geofabrik italy + switzerland + austria + france/rhone-alpes + france/provence-alpes-cote-d-azur, merged with osmium (1.15.0; 4.57 GB, 285 s on the Pi). Admins and time zones are built (they are needed for country access rules); elevation and transit are not. Build on the Pi: 2,068 s, 2,245 tiles.
2. **Costing profile "4x4" (key `4x4.v1`)** for Confirmed legs:
   - `costing: auto`;
   - `use_tracks: 1.0`: forest and farm tracks are allowed and even preferred, because track entries are typically reached by them;
   - `exclude_unpaved: false`;
   - `use_highways: 0.5`, `use_tolls: 0.5`, `use_ferry: 0.5`: neutral defaults (Phase 3 profiles will change them);
   - `country_crossing_cost: 0`, `country_crossing_penalty: 0`: Schengen borders have no controls;
   - `ignore_oneways: false`: always, for safety on mountain roads.
   - Access, closure and restriction tags are honoured, so a Confirmed leg is legal by the map data.
   - One costing serves both objectives. The matrix returns distance and time of the fastest path, and the project objective only selects which value is the arc cost. Switching objective therefore needs no new legs.
   - The permissive variant (Unconfirmed U1) adds `ignore_access: true`, `ignore_closures: true`, `ignore_restrictions: true` (and `ignore_non_vehicular_restrictions` if the pinned version has it).
3. **Snapping control.** Each location in Confirmed and U1 requests carries `search_cutoff = CONFIRMED_SNAP_M` (default 250 m). Valhalla's default (tens of km) would silently hide an off-network gap. Point classification and off-network links are described in ADR-016.
4. **provider_id** = `valhalla:<tileset_last_modified from /status>`, so a tile rebuild invalidates cached legs automatically. **profile** = `4x4.v1` (it changes whenever the costing options change). Both are in the leg-cache key.
5. **Service limits** (raised in `valhalla.json` by the build service):
   - `service_limits.auto.max_matrix_distance`: 2,000,000 m;
   - `thor.costmatrix.allow_second_pass`: **true** (default false). **Mandatory** (SPIKE-2R edge case 1): with the default, 29 of 40 sampled null cells were routable by `/route` and one cell was 33.7 % short; with `true`, 0/40 false nulls and 40/40 distances within 0.01 % of `/route`, at about 2× matrix time. Without it the ladder would negatively cache false None pairs.
   - `service_limits.auto.max_matrix_location_pairs`: keep the default 2,500 (inclusive; 2,501 → error 150). There is **no** `max_matrix_locations` key in 3.9.1 (design finding F-14 closed). The adapter batches to `VALHALLA_MAX_MATRIX_PAIRS` (default 2,500) in rectangular sub-matrices: calls = `ceil(|targets| / floor(2500 / |sources|))`. 60 items one-way = **2 calls** (61×31 + 61×30).
   - `service_limits.auto.max_locations` stays 20, so geometry is fetched per leg, not as one multi-point route.
   - `server_threads`: 2, leaving cores for the app and the solver.
   - The serving container runs with `update_existing_config=False` (True re-merges the config at start and rewrites `mjolnir.concurrency` as a string). The 3.9.1 scripted image runs as root; the build service applies the deltas with `jq`.
6. **Client policy** (`ValhallaRoutingProvider`, httpx):
   - at most 2 concurrent requests;
   - timeouts: connect 2 s, read 120 s for matrix and 30 s for route/locate;
   - **per-call deadline = min(read timeout, time remaining until the job's feasibility limit)** (Revision 2, review M-3). The ADR-014 stage budgets are p95 targets, not deadlines, so a slow call is never aborted just for exceeding its stage row;
   - retry **only** on 5xx, connect errors and timeouts: 3 attempts, backoff 0.5 / 1 / 2 s with jitter;
   - never retry 4xx;
   - a job with any retried call records `retried=true` and is **outside the 180 s p95 claim** (ADR-014).
   - Error mapping:
     - connect error or timeout after retries -> `ProviderUnreachable`;
     - 5xx after retries -> `ProviderUnavailable` ("routing engine not ready / failing");
     - per-location "no suitable edges near location" (error 171, `/route`) -> that point is unsnappable at this level; this is data, not an error;
     - **matrix error 170** ("Locations are in unconnected regions") -> one location in the batch is unsnappable at this level. It fails the **whole** call, so it is **never** recorded as None. Prevention: legal matrix calls contain only points `PointSnapper` classified as legally snappable, sent as their snapped coordinate. If 170 still occurs, the adapter splits the batch (or locates per point) and retries the valid part;
     - error 150 ("Exceeded max locations") -> adapter bug (batch over the pair limit); raised, never mapped to None;
     - "no path" (error 442) or null cells -> no connection at this level (valid only with `allow_second_pass=true`, §5).
   - `/locate` never errors for an unsnappable point: it returns 200 with empty `edges`/`nodes`. Use `verbose: true` to get `edges[].distance` (m).
   - Probe calls bypass the leg counter and never count toward A-4.
7. **Resources** (outside NFR-5, budgeted against the about 11 GB free):
   - Valhalla `mem_limit: 4g`. Measured (SPIKE-2R K3): idle 76 MB after a fresh start, ~1.3 GB steady after load (not returned until restart), peak 1.59 GB VmRSS / 1.41 GB cgroup during the 60-item matrix. Do not go below ~2g;
   - the tile build is capped at `--memory 9g` and runs while serving is stopped. Measured: it **ran at the 9 GiB cap under reclaim pressure** (`memory.peak` = 9 GiB incl. page cache, 0 OOM). No headroom: if the extract grows, raise the cap to 10-11 GB or build on the PC and copy the tiles;
   - `country_crossing_cost` must stay 0: Valhalla adds it to the returned `time`.
   - Disk (measured): PBF 4.57 GB + `valhalla_tiles.tar` 4.4 GB (served, mmapped) + tile dir 4.5 GB (not needed at serve time once the tar exists; the build service may delete it) + admins/timezones 150 MB. Source extracts 4.3 GB can be deleted after the merge.
8. **Startup.** The app does not wait for Valhalla to be healthy (tile loading can take minutes). The provider probe is re-run every 60 s and before each plan job. Until it passes, plan requests are refused with "Routing engine not ready - nothing was changed. Try again shortly."
9. **Later adapters** behind the same port: OpenRouteService hosted (analysis in ADR-002) and any other engine.

## Alternatives considered
- **OpenRouteService hosted** (former ADR-002): low effort, but needs a key and internet, has quota limits (about 3,500 pairs per matrix call, daily caps) and sends coordinates off the LAN. The user rejected it for the MVP. It stays a later adapter and the **final fallback** if SPIKE-2R fails on both the Pi and a PC build (confirmed by the user, D61; needs a key).
- **OSRM self-hosted**: faster matrix, but extracting about 4 GB PBF probably exceeds the Pi's free RAM. Profiles are fixed at preprocessing, so there is no per-request ignore-access retry. No `search_cutoff`-style snap control per request.
- **GraphHopper self-hosted**: no Matrix API in the open-source build; JVM heap of 3-6 GB.
- **Tiles always built on a PC and copied**: avoids Pi build risk, but needs a PC step on every refresh. Kept as the SPIKE-2R fallback.

## Consequences
- Positive: no key, no quota, private; per-request permissive options and snap control make FR-5.8 implementable; the compose stack stays self-contained.
- Negative: a tile build (~34 min, at the 9 GB cap) and quarterly refreshes; about 1.3-1.6 GB RAM in use after the first plan. Cold-matrix latency is measured at p95 10.5 s for 60 items (SPIKE-2R K4), so it is no longer the dominant risk (ADR-014).
- Testing: a shared port contract suite runs against `MockRoutingProvider` and `ValhallaRoutingProvider` (recorded fixtures via respx, plus a scheduled live run against the Pi's Valhalla) to keep error and partial-result semantics identical (review B4). Contract tests are recommended for Valhalla against the pinned image version, which they assert via `/status` (unknown costing options are silently ignored, so a version drift would not error). Recorded fixtures from SPIKE-2R are in `docs/feature/overland-route-planner-mvp/spike/fixtures/`; one must cover "matrix null cell confirmed by `/route` 442" (`matrix_confirmed_with_island_null_row`).

## Amendment (DEVOPS, D95) — 2026-11-02
DV-1, accepted by the user. Read "a scheduled live run against the Pi's Valhalla" as **a manual live run (`make contract-live`) from the Mac**, because GitHub-hosted runners cannot reach the Pi (no inbound access, no runner on the Pi). The same routing-port contract suite runs through an ephemeral loopback forwarder (`valhalla-tunnel`, 127.0.0.1:18002, ops profile) and an ssh tunnel. Valhalla itself stays unpublished (D52). Triggers: slices 06a/06b, any Valhalla image or `valhalla.json` change, every tile refresh. CI keeps replaying the recorded fixtures (blocking). The decision above is unchanged. See `docs/feature/overland-route-planner-mvp/feature-delta.md` "## Wave: DEVOPS".
