# ADR-017: Out-and-back retrace (exit side only)

## Status
Accepted; penalty parameters pending SPIKE-1R (user decision N4, 2026-11-01). Implements the HC-1 "Out-and-back retrace" bullet, FR-5.8 and A-7.

## Context
- HC-1 (2026-11-01): if no road leg at any level leaves a track's exit B toward the next stop, but one leaves its entry A, the planner may drive A->B as stored and then a retrace leg B->A along the same track reversed, then continue from A.
  - The retrace is always Unconfirmed: "retraces the trail backwards; check it is drivable in reverse".
  - It is only used when no road option exists.
  - The mirror case (entering a track at its exit) is never proposed.
- A-7: the plan drives A->B in full, then a retrace leg B->A flagged Unconfirmed, and never drives the track item B->A.

## Decision
1. **Model.** Each track node t has exactly one arrival point (entry). Its departure point for each successor j is decided per arc, as follows:
   - if leg exit(t) -> entry(j) exists at any level: the arc uses it (no retrace);
   - else if leg entry(t) -> entry(j) exists at any level: the arc t->j is a **retrace arc**. Its cost is `W1 * (1 + unconfirmed(entry(t)->entry(j))) + W2 + len/dur(t) + RETRACE_PENALTY + c(entry(t)->entry(j))`;
   - else the arc t->j is forbidden.
   - `RETRACE_PENALTY_M` defaults to 10,000 m and `RETRACE_PENALTY_S` to 1,800 s. They only break ties among equal (unconfirmed, retrace) counts; `W2` already makes a retrace lose to any road alternative with the same Unconfirmed count. The `len/dur(t) + RETRACE_PENALTY + c(entry(t)->entry(j))` part is the arc's `c` in ADR-016 §4: it enters the objective and `max_c` (review M-1). Retrace km still appear in the totals as ordinary off-road km (D57).
   - POIs never get retrace arcs. No arc ever arrives at a track's exit, so the mirror case is structurally impossible.
2. **Pairs.** entry(t) -> entry(j) legs are fetched only for (t, j) where exit(t) -> entry(j) resolved to None. This is a second, small ladder pass. Cached like any leg.
3. **Itinerary.** A retrace arc expands to: the track item row (entry -> exit, full canonical points), then a **retrace leg** row "Retrace <track> (B -> A) - Unconfirmed", then the road leg entry(t) -> entry(j) at its own level.
   - Retrace geometry = the run's snapshot version of the canonical points, reversed (ADR-018). There is no provider call.
   - Retrace distance and time: track length and track duration. They count as **ordinary off-road km/time** in the totals, with no separate breakdown (user decision D57; FR-5.3 amended). The leg itself is still flagged Unconfirmed in the itinerary, Warnings, map and GPX.
4. **Guard (ADR-009 amendment).**
   - The track item is driven entry -> exit, with points equal to the snapshot version.
   - A retrace leg appears only immediately after its own track item, from exit(t) to entry(t), with points equal to the reversed snapshot points, flagged Unconfirmed with reason `retrace`.
   - The direct pair exit(t) -> entry(next) is None in the run's leg snapshot.
   - The following leg starts at entry(t).
   - Any other retrace form is a violation.
5. **Presentation.**
   - Map: the retrace is drawn as an orange dotted line offset from the track, with **no direction arrows of its own**, so the track's canonical arrows stay unambiguous, and a "retrace" label.
   - Warnings: "<track>: retraces the trail backwards; check it is drivable in reverse".
   - GPX: a separate `<trk>` (ADR-010).

## Alternatives considered
- **Never retrace; mark the item unreachable**: contradicts the user decision and HC-1 as amended.
- **Allow the mirror case (enter from exit)**: forbidden by HC-1.
- **Model the retrace as a reversed track variant node**: would put a reversed track into the model, which HC-1 and the §7 model rule ("no reverse variant") forbid. The retrace is a leg, not a track traversal.

## Consequences
- Positive: dead-end trails become plannable without ever reversing the track item; the guard proves the form.
- Negative: more model complexity and one more ladder pass for affected pairs; the totals semantics need confirmation.
- Tests: A-7 (Mock: exit of a track has no leg out, entry has); a mirror-case test (entry unreachable, exit reachable -> item Failed "unreachable"); property tests over sparse random projects asserting no track item is ever driven exit -> entry, and that retraces occur only in the guarded form.
