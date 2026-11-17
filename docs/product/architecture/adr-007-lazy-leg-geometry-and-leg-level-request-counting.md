# ADR-007: Lazy leg geometry and leg-level request counting

## Status
Accepted (user decision, 2026-11-01), **with Amendment 1** (Valhalla, confidence levels, retrace; read it first). Refines the wording of A-4 / US-09 (see feature-delta "Changed Assumptions").

## Context
- A-4 / US-09 S1: excluding an item and recalculating makes **zero** new routing requests. US-09 S2: the number of new legs shown equals the number of routing requests.
- Optimization needs only distance/duration (matrix). The map (FR-6.5) and the GPX export (US-18 S1) need road geometry, but only for the legs actually in the itinerary.
- Excluding an item can change the order and create consecutive pairs whose geometry has never been fetched. If geometry were fetched during Recalculate, A-4 would be broken.
- One ORS matrix HTTP call carries up to 3,500 legs, so "requests" counted as HTTP calls would never equal "new legs". **[ORS framing superseded by Amendment 1: Valhalla batches up to 2,500 pairs; the same argument holds.]**
- ORS directions are rate-limited (about 40/min free tier). **[superseded by Amendment 1: no rate limit with self-hosted Valhalla; concurrency 2.]**

## Decision
1. **Recalculate fetches matrix values only.** Geometry is fetched lazily by `LegGeometryService` when a run's map is opened (`GET /api/plan-runs/{id}/geometry`) or when a GPX export is requested. It is cached in the leg cache (`geometry` column, encoded polyline).
2. **Request counting unit = one leg (one ordered pair) requested through the `RoutingProvider` port**, counted by `CountingRoutingProvider` separately for matrix legs and geometry legs. The plan-run record and log line store `new_legs`, `cached_legs` and `provider_requests_legs` (matrix) **[final gate D130: named `legs_new`, `legs_cached` everywhere — poll payload, `plan_job_log`, plan-run record, log lines]**. HTTP call counts are logged as a diagnostic only.
3. A geometry fetch that fails (unreachable or quota) leaves the run unchanged:
   - the map draws affected legs as dashed straight lines labelled "geometry unavailable";
   - **GPX export is refused** with "Road shapes could not be fetched from the routing provider - export not possible right now. Try again later."
   - MockProvider runs use straight-line geometry by definition and export normally.
4. **Partial matrix results are kept**: legs received before a provider failure are stored in the leg cache (it is a shared cache, not project data). The plan job is refused, no plan run is created, and no project data changes (US-10 S4/S5).
5. ~~The ORS adapter may fetch geometry for a whole itinerary in a few directions calls (waypoint chaining with `skip_segments` over track interiors, verified in the slice-06 spike). Otherwise it issues one call per leg, within the rate limit, with progress shown.~~ **[superseded by Amendment 1: one Valhalla `/route` per leg, at most 2 concurrent; retrace legs need no call.]**

## Alternatives considered
- **Fetch geometry during Recalculate for the chosen legs**: breaks A-4 whenever the order changes.
- **Fetch geometry for every matrix pair**: n(n-1) directions calls (3,540 for 60 items); impossible within quota and pointless.
- **Count HTTP calls**: makes US-09 S2 unverifiable, because one call carries many legs.

## Consequences
- Positive: A-4 holds exactly; quota use is proportional to new legs; geometry is fetched once per leg ever.
- Negative: the first map view or export of a real-provider run needs network and may take time (rate limit); offline export is unavailable.
- Itinerary km come from matrix distances. Geometry length can differ slightly (provider snapping); the run totals are frozen at run time and remain authoritative.

## Amendment 1 (Revision 1, 2026-11-01)
After ADR-013 (Valhalla is the only MVP provider) and ADR-016/017 (confidence levels, retrace):
- "Offline" now means **the routing engine (Valhalla) is unreachable or not ready**. The refused-export message becomes "Road shapes could not be fetched from the routing engine - export not possible right now. Try again later." Map behaviour is unchanged (dashed grey, "geometry unavailable").
- Geometry is fetched per leg from Valhalla `/route` (at most 2 concurrent), with the same costing level that produced the leg (legal or permissive). Off-network links add straight segments. **Retrace legs need no call**: they are the reversed snapshot-version points (ADR-018).
- Geometry is fetched only from a provider whose `provider_id` equals the run's. If the tiles were rebuilt since the run, the geometry is "unavailable" and export is refused with "Routing data changed since this run - recalculate to export".
- **Unconfirmed legs never block export** (FR-5.8). Only missing geometry does.
- Counting: "legs requested" = **distinct pairs per job** at the port (a pair tried at two confidence levels counts once). Point snapping is counted separately as "points located". **Probe calls bypass the counter.**
- §5 (ORS `skip_segments`) no longer applies.
- Partial results (D29): legs and points resolved before a failure are kept, including None results.

## Amendment 2 (slice 09, D251-D256) — 2026-11-17
Design gap check of slice 09 against the code of slice 06a. Decisions 1 and 3 and Amendment 1 stand; this says how the map's road shapes are built in slice 09 and what waits.
- **One endpoint (D251).** `GET /api/plan-runs/{id}/geometry` answers one GeoJSON `FeatureCollection` in itinerary order. Line features: `kind` `road` (the leg into a stop), `track` (a track stop, drawn entry to exit in the direction it is driven), `retrace` (the retrace row, exit back to entry); properties `stop` (the 1-based stop number the line leads to or belongs to), `item_id`, `name`, `level` (`confirmed` | `unconfirmed`, roads and retraces), `reason`, `geometry` (`available` | `unavailable`). Point features: `marker` `stop` (numbered, at the stop's position: a POI's place, a track's entry), `entry` and `exit` (each track), `start_end` (one marker when Start and End are the same item) or `start` and `end`. Track and retrace lines come from the run's snapshot version of the canonical points (ADR-018), thinned for display to at most 1,500 points per track (first and last kept, every n-th between); their direction is the point order. A Failed run answers 404 `not_found` with "This plan run has no route to draw".
- **Road shapes (D252).** The port gains `route_shape(origin, destination) -> list[Coordinate]`. Valhalla: one `/route` per leg with the 4x4 costing, the legal snapped coordinate sent as in the matrix, `shape` decoded from polyline6, at most 2 calls at a time through the same process-wide limit, the same retry and error mapping; an answer without a route (442, 171) is a straight line marked `unavailable`. The offline road map: the straight line. Shapes are kept in memory per `(provider_id, profile, pair)` for the process's life, like the legs; persistence is slice 05.
- **When shapes cannot be fetched (D253, D28 kept).** The road map's identity differs from the run's stored `provider_id` (map data rebuilt, or the engine of another version) -> every road leg is a straight line marked `unavailable`, no call is made; the engine unreachable or failing -> the legs not yet fetched are straight lines marked `unavailable`, the answer is still 200 and the run is unchanged. Track and retrace lines never depend on the engine. GPX export is unchanged in this slice: it still writes no road shapes (slice 11 owns the device GPX).
- **K5 end (D254, closes D236).** Each answer logs `plan.run.geometry_served` with `plan_run_id`, `legs`, `legs_fetched`, `unavailable` and `served_ms`; `make perf-pi MODE=e2e` ends a measured run when the geometry answer is received.
- **Not in this slice:** the Warnings section on the map page (slice 08), the duplicate-POI warning of FR-8.3 (slice 08), a reversed track (slice 08).
