# Overland Route Planner MVP, slice 02: direction-safe optimizer

Date: 2026-11-09. Release `c81c426` (tag `slice-02`, image `sha256:272b30ee…`), schema 0006, deployed on pi-host. The feature `overland-route-planner-mvp` continues with slice 03; this is a slice archive, and the workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

Marco's multi-track project is now ordered by an optimizer that never reverses or cuts a track, always starts at Start and ends at End, refuses to run without both anchors, and gives the same plan for identical inputs. A plan run carries an itinerary (legs, track length, off-road time, cumulative distance and time) and road / off-road totals. The web page shows them, and so does a phone-width layout.

Stories: US-03 (trails driven whole and as recorded), US-04 (fixed anchors), US-05 (same inputs give the same plan, with honest totals). Hard constraints exercised: HC-1, HC-2, HC-5, with A-1, A-2 and A-6 as property tests.

## Business context

The slice tests the learning hypothesis "the directional, fixed-anchor model can be expressed without reverse nodes". None of the 1,000 random cases per property produced a reversed track, a moved anchor or a different plan, so the hypothesis survives. In the dogfood check on the Pi, the real Assietta file was driven entry -> exit in every run, including one where the anchors made the reverse free (0 km of road against 2 x 50.36 km).

## Key decisions (feature-delta.md, DELIVER Upstream Issues)

| ID | Decision |
|---|---|
| D214 | The pre-slice spike S4 was replaced by a 30-minute Mac timing probe (`spike/s4-property-budget-probe.md`). Its three questions had been answered by SPIKE-1R and the 01b solver; the probe measured property-test runtime |
| D215 | The HC-1, HC-5 and A-2 properties solve at `solution_limit` 100 (same model and strategy as production) |
| D216 | A-6 runs at the production budget, tagged `@slow`, in its own CI job (`slow-properties`); publish needs it |
| D217 | The Stale scenario gained a Given that computes a plan run |
| D218 | The fingerprint memo stays; the rule-breaking scenario re-optimises with `ignore_memo` |
| D219 | FR-2.4 (place names in track rows) stays out of slice 02; rows show coordinates |
| D220 | Defaults accepted: HC-3 as the evidence in the rule-breaking scenario; codes shown as words until product wording exists; PyYAML a runtime dependency; unscripted mock pairs at 60 km/h; item removal and off-road speed are API only; 15 km/h fixed in the domain |
| D221 | CI job 2 exceeded its 20-minute timeout once the slice was enabled. The three HC properties got the `heavy_property` marker and moved to the slow job; job 2 target became 15 min |

## Steps completed (roadmap phase 05, 12 steps, 30 h planned against the brief's 1 day)

| Step | Commit | Outcome |
|---|---|---|
| 05-01 | `86f77e5` | Item removal, nullable anchors, `?type=` filter |
| 05-02 | `3b60f18` | Stale plan marking |
| 05-03 | `88610f9` | Off-road speed stored in project settings |
| 05-04 | `7568e52` | RoadMeasure, scripted MOCK_PLAN YAML, provider id with script hash |
| 05-05 | `370c805` | Totals and itinerary columns; guard checks leg length and time |
| 05-06 | `dc12e60` | Migration 0006: totals, report, fingerprint, memo_hit |
| 05-07 | `e2ae07d` | Per-stop columns persisted |
| 05-08 | `5f2d1e7` | Failure report in product words |
| 05-09 | `aa02e1f` | `ignore_memo` |
| 05-10 | `0aaa690` | Fingerprint `fp1` and FingerprintMemo |
| 05-11 | `4318ca0` | Web itinerary and totals, `duration.ts` |
| 05-12 | `44b0ebc` | `@pending` removed, `slow-properties` CI job |

All 49 steps of the feature's roadmap so far are traced; `des-verify-integrity` exit 0.

## Quality gates

| Gate | Result |
|---|---|
| Refactor L1-L6 | 15 commits `9b888ef` .. `0366a21`; OpenAPI snapshot unchanged |
| Adversarial review | Two passes, NEEDS_REVISION each; findings fixed in `c6092b7` .. `582e352` and `19d65f7` .. `fc793e3`; F1 rejected (01b writer always stored every stop key); golden fingerprint verified independently |
| Mutation | 98.9 % (1211/1224) over 21 domain and application files, `BASE=slice-01b`; no real survivor in InvariantGuard or SolverModelBuilder |
| Suite | 567 passed locally; CI run 42609468929 all green: job 2 13.6 min, slow-properties 15.9 min, mutation 51.4 min |
| Demo | `feature-delta.md`, "Slice 02 demo on pi-host": every automated story check passed on the Pi |

## Lessons learned

- **Run every command from the repo root during a step.** The DES hooks resolve their paths from the working directory; a shell left in `.nwave/des` sent 05-01's hook logs to a nested directory and its stop validation never ran (UI-DELIVER-5).
- **Property-test oracles need the same care as production.** The memo property failed twice on correct production code: it treated an empty visited order as missing, then expected legs that no plan drives (UI-DELIVER-6, fixes `0391a87`, `3325621`).
- **Measure CI time per selection before enabling a slice.** Enabling slice 02 pushed job 2 past its timeout; the property cost (171 s locally, more in CI) had been measured but not added to job 2's budget (D221).
- **No push while an agent or mutation run is active.** The pre-push hook tests the working tree and stashes unstaged files.
- **External downloads fail independently of the code.** Trivy and lint failed on HTTP 504 from GitHub releases for a day; the later run passed with no change.

## Open items carried to later slices

- US-02b "The first plan opens in OsmAnd" and Giulia's phone check: NOT RUN, no device (K6 unproven).
- FR-2.4 / D202 / D219: track rows show coordinates, not place names.
- D210: NaN and inf elevations, slice 08.
- No project or run delete: the two slice-02 demo projects and 01b's run 2 stay on the Pi.
- The real Jafferau and Maira-Varaita recordings do not exist yet; the demo used synthetic fixtures for them.

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-02-directional-optimizer.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-02-directional-optimizer.feature`
- Decisions, gates and demo evidence: `docs/feature/overland-route-planner-mvp/feature-delta.md`
- ADRs: `docs/product/architecture/adr-005-deterministic-solver-budget-ceiling-fingerprint.md`, `adr-009-hc-invariant-guard.md`, `adr-014-performance-limits-determinism.md`, `adr-015-plan-job-lifecycle-incumbents-stop.md`
- Timing probe: `docs/feature/overland-route-planner-mvp/spike/s4-property-budget-probe.md`
