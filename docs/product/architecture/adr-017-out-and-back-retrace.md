# ADR-017: Out-and-back retrace (exit side only)

## Status
Accepted (user decision N4, 2026-11-01). Penalty measured by SPIKE-1R (`RETRACE_PENALTY_M` = 10,000 kept; D78). **Final-gate amendment** D125/D134 (2026-11-02). **Amendment 2** (slice 03b as built: per-arc rule, single-phase weights, no retrace km or penalty in the objective, retrace is a stops row; ruling 2026-11-10, Decision 18 accepted 2026-11-11). Implements the HC-1 "Out-and-back retrace" bullet, FR-5.8 and A-7.

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
   - `RETRACE_PENALTY_M` defaults to 10,000 m and `RETRACE_PENALTY_S` to 1,800 s. They only break ties among equal (unconfirmed, retrace) counts; `W2` already makes a retrace lose to any road alternative with the same Unconfirmed count. The `len/dur(t) + RETRACE_PENALTY + c(entry(t)->entry(j))` part is the arc's `c` in ADR-016 §4: it enters the objective and `max_c` (review M-1). Retrace km still appear in the totals as ordinary off-road km (D57). **[Final gate D125 (UD-4) corrects the contradiction: `RETRACE_PENALTY` enters only the solver's internal arc cost and `max_c`, as a tie-break; it never enters the reported objective, Totals or itinerary. Reported objective = road + retrace km (or time); see the amendment below.]**
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

## Amendment (final gate, D125, D134) — 2026-11-02
- **Penalty is a tie-break only (UD-4, R-05/R-06).** Order: fewest Unconfirmed legs (the retrace leg counts as one), then fewest retraces, then the objective (ADR-016 amendment). `RETRACE_PENALTY_M = 10,000` (SPIKE-1R; `RETRACE_PENALTY_S = 1,800` not exercised) is added to a retrace arc's cost **inside the solver model only**. It is never shown or stored as a result value.
- **What the itinerary and Totals show.** The retrace leg row shows the real retrace km/time (= track length/duration of version n). Totals: road km/time = road legs only; off-road km/time = track items + retraces (D57). The run's reported objective = road + retrace km (or time), without the penalty.
- **Guard check 5 (D134, R-16).** The leg that follows a retrace leg starts at entry(t), so its reference pair in the leg snapshot is entry(t) -> entry(next), not exit(t) -> entry(next). See ADR-009 Amendment 3.

## Amendment 2 (slice 03b, as built; ruling of 2026-11-10; Decision 18) — 2026-11-11
The final-gate amendment above counts as Amendment 1. This records slice 03b, roadmap steps 07-01..07-10 (commits 711c1fb 07-01, fbe7225 07-02, cd53c20 07-03, f723cca 07-04, d01780c 07-05, 49caabd 07-06, ac80684 07-07, 49e57f2 07-08, 6eb346a 07-09, 5c751a8 07-10; commit ids as of the 03b branch before push, they may be restacked). Where it differs from section 1 or Amendment 1, this amendment governs; section 1 and Amendment 1 stay readable above.

**1. Per-arc rule, one definition (supersedes the wording of section 1 and section 2).** `domain/planning/retrace_rule.py` holds it and nothing else decides it:
- `arc_kind(previous, successor, legs)` returns `road` when exit(previous) -> entry(successor) is connected, else `retrace` when `second_pass_pair` exists and is connected, else `forbidden`;
- `second_pass_pair(previous, successor, legs)` returns entry(t) -> entry(j) only for a track whose entry differs from its exit (a loop never retraces) and with no road from its exit toward the successor; otherwise none. It is also the pair the plan job asks in the second ladder pass.
The solver model builder, the plan job, the assembler and the guard (ADR-009 check 6) all call it.

**2. Objective: road km only (ruling 2026-11-10; supersedes the retrace cost in section 1 and the reported-objective text in Amendment 1).** Third criterion = road km (or road time). Retrace km are **not** in the objective: a retrace arc's `c` is the metres of the road leg entry(t) -> entry(j) only, with no track length. `RETRACE_PENALTY_M`/`_S` is **dropped** as redundant under W2: W2 already makes a retrace lose to any road alternative with the same Unconfirmed count, and no tie remains that a penalty would break. The reported objective (itinerary, Totals, run `objective`, `incumbent.objective`, diagnostics, GPX) is road metres only. Totals still count a retraced track's km and time as off-road, as before (D57). The `RETRACE_PENALTY_*` keys no longer drive anything. **Ties between plans that retrace different tracks are allowed**: nothing prefers one retraced track over another once counts and road km are equal.

**3. Weights until two-phase exists (single-phase, Decision 18).** With N the number of arcs in a tour and `c_max` the largest `c` over all arcs: `W2 = (N+1) * c_max + 1` and `W1 = (N+1) * (W2 + c_max) + 1`. Every arc costs `W1 * (its Unconfirmed legs, the retrace leg counting one) + W2 * (its retraces, 0 or 1) + c`, so a Confirmed road arc costs its plain metres, in one search (`SINGLE_PHASE`, `domain/planning/solver_model_builder.py`). Counts therefore stay strict. The two-phase solve of ADR-016 section 4 is **not built** in 03b; it stays with slices 06a/06b. See ADR-016 Amendment 2 for the risk and its acceptance.

**4. Retrace row (section 3 as built).** A retrace is a **row of the stops list**: `type` `retrace`, `item_id` that of its track, placed directly after the track row. It leaves the track's exit and ends at its entry, is not a road leg (no `leg_*` fields), carries its own `confidence` (Unconfirmed), `reason` and `retrace_sha256` (ADR-009 Amendment 4), and its km and time are the track's, counted as off-road. The following road leg starts at entry(t). The retrace is not a track traversal and not counted by HC-3.

**5. Presentation as built.** The GPX export writes the retrace as its own `<trk>` of kind `retrace`, with the trail's stored points reversed (the only track written reversed), and names every Unconfirmed leg, road or retrace, with the suffix `[UNCONFIRMED - <reason>]` (ADR-010; `domain/export/gpx_document_builder.py`, step 07-09). An export of a plan with a retrace row no longer fails (fixed in 6eb346a).

**Evidence from the build.** Sparse real-child property (a real OR-Tools child on sparse projects, compared with brute force): the optimum was found in 20 of 20 cases, road-km gap +0.00 %. Golden order unchanged; matrix pins of step 07-01 (`tests/perf/golden_model_pins.json`) unchanged. HC-1 property over levels with retrace adjacency (5c751a8).
