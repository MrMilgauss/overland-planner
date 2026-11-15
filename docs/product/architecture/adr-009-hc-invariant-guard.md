# ADR-009: HC invariant guard on every plan run

## Status
Accepted (2026-11-01), **with Amendment 1** (versioned inputs, leg snapshot, retrace form, logging boundary) and **Amendment 2** (full-sequence hashes), and **Amendment 3** (final gate: check 5 after a retrace; hashing cost), and **Amendment 4** (slice 03b as built: `retrace_sha256`, check 6, check 5 after a retrace, reachability claims; 2026-11-11).

## Context
- HC-1..HC-5 are non-negotiable. K2/K3 require 0 violations, measured by property tests **and a per-run invariant check in the logs** (US-03, US-04, US-08 KPIs).
- The solver is a third-party library behind a port. A model-building bug, a solver regression or a memo reuse on stale data could silently produce a wrong plan. Earned Trust: the solution must prove that it satisfies the hard constraints before anyone sees it.

## Decision
`InvariantGuard` (pure domain service) runs on every candidate plan before persistence: after a solve and after a memo hit. It checks:
1. **HC-2**: the first stop is the Start and the last stop is the End; both are POIs (D6); a round trip is one item at the first and last positions.
2. **HC-3 / FR-5.4**: every Included non-anchor item appears exactly once; no Excluded item appears. The consideration report lists every project item exactly once with the status matching its snapshot flag (Included with positions, Excluded, or Failed with reason). Included = placed + failed.
3. **HC-1**: each track stop's entry and exit equal the snapshot's canonical entry and exit for its `direction_version`. The leg into a track ends at its entry; the leg out starts at its exit. No reversed variant exists in the model.
4. **HC-5**: each track stop references the full canonical point list (point count and first/last point equal the stored canonical file); its off-road length equals the stored track length.
5. **Leg consistency**: each itinerary leg i -> i+1 is the cached leg exit(i) -> entry(i+1) for the run's provider_id and profile.

On any violation the run is persisted as **Failed** with reason `internal invariant violation (<rule>)`. It shows no itinerary and no export, the previous successful run stays current, and an `invariant.violation` error event is logged with the rule and the item ids. On success the log line `plan.run.completed` includes `invariants: "ok"`.

The same guard functions are used as oracles in the 1,000-case property tests (US-03 S2/S3, US-04 S1, US-07b S2).

## Alternatives considered
- **Trust the solver model (tests only)**: tests cover generated inputs, not every real run; the KPIs explicitly require a per-run check.
- **Guard in the HTTP layer / UI**: too late, and it would be duplicated for the CLI (Phase 2).
- **Assertions inside the OR-Tools adapter**: couples the guarantee to one solver; the guard must survive a solver swap (D14 kill criterion).

## Consequences
- Positive: a hard guarantee independent of the solver; direct evidence for K2/K3 in logs.
- Negative: a few milliseconds per run and a file read per track (point counts are cached in the track record and cross-checked against the file).

## Amendment 1 (Revision 1, 2026-11-01)
- **Versioned inputs (ADR-018).** Checks 3-4 read the canonical file of the snapshot's `direction_version` and verify `point_count` and `canonical_sha256` from the snapshot. They do not read "the current file".
- **Leg consistency (check 5).** The leg snapshot stored on the run is the reference, not the live cache. Each leg's level and reasons must match the snapshot. A leg whose pair is None in the snapshot must not appear. The run's Unconfirmed count must equal the number of legs listed under Warnings.
- **Retrace legs (ADR-017), new check 6.** A retrace leg is allowed only:
  - immediately after its own track item;
  - from exit(t) to entry(t), with points equal to the reversed snapshot points;
  - flagged Unconfirmed with reason `retrace`;
  - when the pair exit(t) -> entry(next) is None in the leg snapshot;
  - with the following leg starting at entry(t).
  No leg may end at a track's exit (no mirror case). The track item itself always passes check 3 (entry -> exit).
- **Reachability failures (ADR-016 §3).** Every item reported Failed "unreachable" must indeed have no in-arc or out-arc, or be disconnected from Start or End, in the run's arc snapshot.
- **Logging boundary (Amendment 1, unchanged by Amendment 2).** `InvariantGuard` stays pure and returns a `GuardResult`. `PlanRequestJob` (application) emits `invariant.check` / `invariant.violation` through an `EventLog` port (adapter: structlog). The domain imports no logging library.

## Amendment 2 (Revision 2, 2026-11-01): full-sequence proof (review M-2)
- The **itinerary snapshot** records, for every track stop, `track_id`, `direction_version`, `point_count` and `canonical_sha256`. For every retrace leg it records `retrace_sha256`: the SHA-256 of the canonical serialisation of the reversed point list of that same version.
- Check 4 (HC-5) and check 6 (retrace) compare the **full-sequence hash** of the points read by version against these values. Count and first/last points are no longer the only checks, so a mid-sequence edit or truncation is caught.
- GPX export and the map recompute and verify the same hashes before emitting points. A mismatch refuses the export with "Track data for this run is inconsistent - recalculate", and an `invariant.violation` event is logged.

## Amendment 3 (final gate, D134, D135) — 2026-11-02
- **Check 5 exemption after a retrace (R-16, F-7).** For the leg that immediately follows a retrace leg of track t, the reference pair is **entry(t) -> entry(next)** in the leg snapshot (its level and reasons must match), not exit(t) -> entry(next). Check 6 already requires exit(t) -> entry(next) to be None. All other legs keep the exit(i) -> entry(i+1) rule. Property tests cover runs with 0, 1 and 2 retraces.
- **Hashing cost (R-17, F-5).** The guard's full-sequence hashing is re-measured at slice 03 with 40 × 20,000-point tracks (ADR-014 amendment D135). If the 3 s row is exceeded, an import limit on points per track is introduced; the checks themselves are never weakened.

## Amendment 4 (slice 03b, as built) — 2026-11-11
Records what slice 03b built for Amendments 1-3 (roadmap steps 07-01..07-10; commits 711c1fb 07-01, fbe7225 07-02, cd53c20 07-03, f723cca 07-04, d01780c 07-05, 49caabd 07-06, ac80684 07-07, 49e57f2 07-08, 6eb346a 07-09, 5c751a8 07-10; commit ids as of the 03b branch before push, they may be restacked). It adds no check. Code: `domain/planning/invariant_guard.py`, `domain/planning/retrace_rule.py`, `application/catalog/track_import_service.py`.
- **`retrace_sha256` as built.** It is the SHA-256 of the canonical serialisation of the reversed points of the **same direction version**, using the same serialiser as the canonical file: `reversed_points_sha256(points)` = hash of `canonical_points_file(reversed(points))`. It is computed from the file read by the snapshot's `direction_version` (never the current file), stored on the retrace row of the itinerary snapshot, and recomputed by the guard (as `reversed_sha256` of the file evidence, for a retraced track only) and by GPX export, which refuses with "Track data for this run is inconsistent" on a mismatch.
- **Check 6, retrace form (`GuardCheck` `retrace`, class `_RetraceForm`).** For every retrace row of a plan, all must hold:
  - it is directly after its own track row, and not first or last;
  - its entry is the track's exit and its exit is the track's entry (it leaves the exit and ends at the entry), with confidence Unconfirmed, the fixed reason (`RETRACE_REASON`: "retraces the trail backwards; check it is drivable in reverse"), the track's stored length as `track_km`, and `retrace_sha256` equal to the hash of the reversed file points just read;
  - it carries no road leg fields (`leg_km`, `leg_s`, `leg_confidence`, `leg_reason`) and no location;
  - the arc from the track to the next stop is a retrace arc by the retrace rule (`arc_kind` = `retrace`): no road from the exit toward the next stop, one from the entry. The rule is defined once in `retrace_rule.py` (`arc_kind`, `second_pass_pair`; ADR-017 Amendment 2) and used by the solver model, the plan job (which pairs to ask in the second pass), the assembler and the guard.
  Any other retrace row is a violation `retrace`. A retrace row is not a track traversal: HC-1, HC-3 and HC-5 judge the stops other than retraces.
- **Check 5 after a retrace as built (`GuardCheck` `leg_consistency`).** The retrace row itself is skipped by check 5 (check 6 judged it). For the road leg that follows it, the reference pair is the retrace rule's `second_pass_pair`: entry(t) -> entry(next). All other legs use exit(i) -> entry(i+1). A pair absent from the leg table is a violation. As the code says, this is a consistency check between the stops and the job's leg table; it does not prove the table right.
- **Reachability claims (`GuardCheck` `reachability`, `check_unreachable`).** A Failed run with reason `unreachable` is checked before it is stored: each item it names must have no path from the Start or none to the End. The guard re-derives this from the leg table with its own search (arcs by the retrace rule), **not** from the tour model or `domain/planning/reachability.py` that made the claim. A named item that an order does connect, or that is not a visited item, is a violation.
- `GuardCheck` values as built: `HC-1`, `HC-2`, `HC-3`, `HC-5`, `leg_consistency`, `retrace`, `reachability`. The numbering in the Decision list (1-5) maps to HC-2, HC-3, HC-1, HC-5, `leg_consistency`; Amendment 1's check 6 is `retrace`.
- The 20,000-point hashing cost row is decided separately (feature-delta D230, 2026-11-10: guard_persist gate <= 5 s, no import cap). Not part of this amendment.
