# ADR-009: HC invariant guard on every plan run

## Status
Accepted (2026-11-01), **with Amendment 1** (versioned inputs, leg snapshot, retrace form, logging boundary) and **Amendment 2** (full-sequence hashes).

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
