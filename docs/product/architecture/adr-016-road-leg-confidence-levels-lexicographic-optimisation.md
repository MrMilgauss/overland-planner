# ADR-016: Road-leg confidence levels and lexicographic optimisation

## Status
Accepted (user decision N3, 2026-11-01). **Amended after SPIKE-1R/2R** (D78, D79, 2026-11-02): dual-costing point classification, legally snapped coordinates for permissive retries, two-phase weighting as default. Implements FR-5.8 and FR-8.2 (revised). Supersedes D39 (the old "any unroutable pair fails the run" proposal).

## Context
- FR-5.8: Confirmed -> Unconfirmed -> None.
  - Unconfirmed is used only when Confirmed has no connection. It is one of: a request ignoring access/closure/restriction tags; a short off-network link from the nearest road to a track entry/exit or POI; an out-and-back retrace (ADR-017).
  - Unconfirmed legs get a distinct map style, are listed under Warnings as "check on the ground", are marked in the GPX leg name, and do not block export.
- FR-8.2 (revised): a run fails only if an Included item cannot be connected at any level in any order, and the failure names that item. A single missing pair never fails a run.
- The optimiser must prefer zero Unconfirmed legs, then minimise the objective.

## Decision

### 1. Point snapping stage (`PointSnapper`, application/routing)
Every new entry/exit/POI point is located once per provider_id/profile and cached in `point_cache`, **with both legal (`4x4.v1`) and permissive costing** in one batched `/locate` each (`verbose: true` for `edges[].distance`; 122 points per call is fine, and an unsnappable point returns empty `edges`, not an error). Locating legally only misclassified 9 of 102 SPIKE-2R points: they lie ≤ 250 m from an access-restricted road but km from a legal one, so a U1 leg exists while a legal-only check would give a long straight link or None. The cache stores, per point, the legal snap (coordinate + distance) and the permissive snap. The class is taken from the **nearer** of the two; the legal/permissive origin is kept for the ladder. Classes:
- **on_network**: nearest routable edge <= `CONFIRMED_SNAP_M` (default 250 m);
- **near**: <= `OFFNETWORK_LINK_MAX_M` (default 1,500 m). The point is routed from its snapped road point plus a straight link;
- **far**: beyond 1,500 m. No road connection at any level. A far track exit can still be served by a retrace (ADR-017).

Snapping requests are counted as "points located", separately from legs (A-4 counts legs). The snap distance is stored, ready for FR-8.1 warnings in Phase 2.

### 2. Pair ladder (`LegResolver`, application/routing)
Only for pairs missing from the cache. All passes are batched.

| Level | Condition | Request | Reason stored |
|---|---|---|---|
| Confirmed | both endpoints on_network | legal costing `4x4.v1` | - |
| Unconfirmed U1 | Confirmed returned none, or an endpoint is on_network only permissively; both on_network | permissive costing (`ignore_access/closures/restrictions/non_vehicular_restrictions`) | `ignores_access_restrictions` |
| Unconfirmed U2 | at least one endpoint near | legal costing between snapped road points, then permissive if none; plus straight links | `offnetwork_link:<m>` (+ `ignores_access_restrictions` if the permissive pass was needed) |
| None | nothing found, or an endpoint is far | - | `no_connection` |

- **Coordinates sent per level (SPIKE-2R edge cases 2 and 4).** Legal (Confirmed, U2 legal) calls contain only legally snappable points, sent as their **legal snapped coordinate**; one unsnappable point would fail the whole matrix call with error 170. Permissive (U1, U2 permissive) calls send the **legal snapped coordinate** for every endpoint that has one, and the permissive snap only for an endpoint that has no legal snap within its class distance. Sending raw points with `ignore_access=true` lets Valhalla snap onto footways (e.g. Briançon → Place d'Armes footway) and returns 442 although a legal route exists.
- A None from the matrix is trusted only because `allow_second_pass=true` (ADR-013 §5).
- User-facing text for `offnetwork_link:<m>`: "entry is X km from the nearest road" (or "exit", or "POI is"). The full form is "Track 'X' entry is 1.2 km from the nearest road — Unconfirmed, check on the ground" (U33, FR-8.1 style).
- Link distance is added to the leg distance. Link duration = link length / project off-road speed.
- A leg-cache entry stores `level`, `reasons[]`, `distance_m`, `duration_s`, `link_m`, `levels_tried`, and nullable geometry. **None results are cached too** (negative caching), so a Recalculate never re-asks. Clearing the cache removes them.
- The counter counts **distinct pairs per job** ("legs requested"). A pair tried at two levels counts once, so US-09 S2's "new legs = legs requested" equality holds. Per-pass request counts are logged as diagnostics.

### 3. Reachability check (FR-8.2) before solving
Build the arc graph: Confirmed + Unconfirmed arcs, plus retrace arcs (ADR-017). Every Included non-anchor item must have an incoming and an outgoing arc, be reachable from Start, and reach End. **Start needs an out-arc only; End needs an in-arc only** (review L-3). For a round-trip S/E item, it needs one out-arc as Start and one in-arc as End.
- Items failing the check -> a numbered **Failed** run, before any solve. The message names each item: "'Isola del Giglio' cannot be connected to any other stop at any confidence level". The report marks the item Failed with reason "unreachable".
- This check is necessary but not sufficient. A rare instance that passes it can still have no valid order; it then runs into the feasibility limit (ADR-014).

### 4. Lexicographic cost (`SolverModelBuilder`, domain/planning)
Arc cost = `W1 * unconfirmed(arc) + W2 * retrace(arc) + c(arc)`.
- `c` is in integer metres or seconds according to the objective. It is the **full** arc cost (Revision 2, review M-1):
  - a road arc: the leg cost;
  - a retrace arc (ADR-017): track length (or duration) + `RETRACE_PENALTY` + the onward leg entry(t) -> entry(j).
  So the **objective minimises road distance plus retrace distance** (or road time plus retrace time), and a retrace is never "free". Off-road km of track items are constant whatever the order (FR-5.3) and stay out of `c`.
- `max_c` = the maximum of `c` over **all** arcs of the model, retrace arcs included.
- `W2 = (N+1) * max_c + 1` and `W1 = (N+1) * (W2 + max_c) + 1`, computed per model (N = number of arcs in a tour). This makes the order strict: fewer Unconfirmed legs, then fewer retraces, then the objective. All values fit in int64 at 60 items.
- **None** arcs are forbidden in the model (`NextVar(i).RemoveValue(j)`); they are not failures.
- **Two-phase solve is the default (D78)**, because SPIKE-1R showed guided local search degrading with big weights: on the sparse instance the single-objective big-W model stalls at +2.57 % road km from ~3,000 to 10,000 solutions, while two-phase reaches +0.28 % at the same budget with the same worst-case time (dense p95 47.4 s vs 47.6 s; sparse 35.6 s vs 21.6 s). Phase 1 minimises Unconfirmed count U* (and retrace count R*, same weights) with limit `SOLVER_BUDGET / 10`. Phase 2 adds an "unconfirmed" dimension capped at U* (and retraces capped at R*) and minimises the objective with limit `SOLVER_BUDGET`. Same port; adapter-internal. The single-phase W1/W2 model stays as the phase-1 cost and as the documented alternative (with `GLOBAL_CHEAPEST_ARC`: +0.71 %).
- **Mandatory nodes** (REQUIREMENTS §7: no disjunction penalties). If every first-solution strategy fails on a sparse instance (`ROUTING_FAIL`), an optional fallback mode uses disjunction penalties far above `W1` purely as a feasibility-search aid. A route that skips an item is never accepted as valid. **Approved by the user (D56)** as a hidden search aid, behind config. It is enabled only if SPIKE-1R shows it is needed (REQUIREMENTS §7 annotated). **SPIKE-1R: not needed** — `PATH_CHEAPEST_ARC` and eight other strategies never failed on 20 sparse variants, so the mode is not built in the MVP. Snap thresholds of 250 m and 1,500 m were confirmed by the user (D59).

### 5. Presentation
- Itinerary rows carry the level and reasons.
- Results Warnings list each Unconfirmed leg: "Leg 4: Briancon -> Strada dell'Assietta - Unconfirmed: entry is 1.2 km from the nearest road - check on the ground".
- Map: Confirmed solid; Unconfirmed orange dotted with a "!" badge; retrace in its own style (ADR-017); "geometry unavailable" grey dashed (ADR-007).
- GPX names are given in ADR-010. Export is not blocked by Unconfirmed legs.

## Alternatives considered
- **Fail the run on any unroutable pair** (old D39): contradicts FR-8.2 (revised).
- **Weighted sum with a modest penalty instead of lexicographic**: lets a big objective saving buy an Unconfirmed leg, which contradicts "prefer zero".
- **Rely on Valhalla's default snapping (35 km search)**: hides off-network gaps as Confirmed legs, which is dishonest towards the user.
- **Open-terrain routing for links**: out of scope (REQUIREMENTS §9); straight links are flagged instead.

## Consequences
- Positive: plans exist whenever they physically can; every compromise is visible and explained; caching covers all levels.
- Negative: up to 2 extra matrix passes for missing pairs (budgeted at 15 s); a more complex model (weights, forbidden arcs); the snap thresholds are heuristics the user may tune.
- The MockRoutingProvider must script levels, snap classes and None pairs per pair and per point (MockRoutingProvider fault and level plan, brief §6) so all of this is testable offline.
