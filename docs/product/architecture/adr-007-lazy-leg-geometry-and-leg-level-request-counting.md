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
2. **Request counting unit = one leg (one ordered pair) requested through the `RoutingProvider` port**, counted by `CountingRoutingProvider` separately for matrix legs and geometry legs. The plan-run record and log line store `new_legs`, `cached_legs` and `provider_requests_legs` (matrix). HTTP call counts are logged as a diagnostic only.
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
