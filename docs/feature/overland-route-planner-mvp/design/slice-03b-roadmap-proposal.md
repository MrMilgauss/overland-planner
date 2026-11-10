# Slice 03b roadmap proposal: dead-end trails are retraced, never reversed

Status: PROPOSED (architect, 2026-11-10). Not reviewed, not approved, not enabled. The matching phase 07 is in `deliver/roadmap.json`, marked PROPOSED. Nothing outside the roadmap and this note was changed; the feature file and `spike/` are untouched.

## 1. What Marco gets (plain language)

- A dead-end pass such as the Colle del Sommeiller can finally be in his trip. The plan drives it up, from the start of the trail, then drives back down the same trail as a separate line ("Retrace Colle del Sommeiller ... Unconfirmed: check it is drivable in reverse"), then carries on from the bottom.
- The planner never starts a trail from its top. If it cannot reach the bottom of a trail by any road, it says so and refuses to plan ("Plan run #N failed: 'Valle Stretta' cannot be connected to any other stop at any confidence level"). The run fails before any long calculation.
- The retrace is used only when no road, not even a doubtful one, leaves the top. If a doubtful road exists, the plan uses it and shows it as Unconfirmed instead.
- Preference order when plans differ (user ruling 2026-11-10): fewest doubtful legs first (a retrace is one doubtful leg), then fewest retraces, then the shortest road driving. The retrace's own kilometres are reported and counted as off-road driving but do not influence the order. A shorter plan never buys an extra doubtful leg or retrace.
- The retrace counts as ordinary off-road driving in the totals at the trail's own length (12.4 km for the Sommeiller) and its time. There is no retrace penalty any more; nothing hidden is ever added to a kilometre or time.
- Each road leg now says whether it is Confirmed or Unconfirmed.
- The GPX file (user ruling 2026-11-10): the retrace is written as its own leg named Unconfirmed, and every Unconfirmed leg, retrace or road, is marked in its leg name "[UNCONFIRMED - reason]". The leg after a retrace works. Not in this slice: the retrace in Warnings (slice 08) or on the map (09); the itinerary list shows the new row.
- Stays safe: plans that have no dead ends, including the two 60-item golden instances, come out exactly as before. No data migration and no deploy step are needed.

Size: 13 steps, about 43 hours (feature work 37 h, carry-overs 6 h), against the brief's 0.8-1 day (6.4-8 h). The brief did not count several pieces the scenarios need (see the phase description): the "unreachable" check, the guard proof, the two-pass road look-up, the GPX marking and screen row, and the CI work. This is the same kind of gap phases 05 and 06 recorded.

## 2. Step overview

| Step | What | h | Turns green |
|---|---|---|---|
| 07-01 | Pin the golden model and order before any change | 1.5 | none |
| 07-02 | Offline road map reads a level per pair (confirmed / unconfirmed:reason / none) | 3 | none (first failure of all 7 moves) |
| 07-03 | Leg table and resolver keep levels and "no road"; one retrace rule; second-pass pairs | 3 | none |
| 07-04 | Solver model: retrace arcs, ordering (Unconfirmed, retraces, road km only), criterion 2 isolated, real-child sparse property | 5.5 | none |
| 07-05 | Unreachable item fails the run, named | 3.5 | #2 never entered from its exit |
| 07-06 | Retrace row, leg_confidence, honest totals | 4 | #3 no retrace when a road leaves, #6 fewer retraces |
| 07-07 | Guard proves the retrace form and hash | 4.5 | #1, #4, #5 (and #7 pinned examples at dev) |
| 07-08 | Real objective and retrace counts in job line and log | 2.5 | none |
| 07-09 | GPX writes the retrace leg and marks every Unconfirmed leg; web itinerary shows them | 4.5 | none |
| 07-10 | HC-1 property over levels, retrace adjacency, timed at ci | 2.5 | #7 verified at 1,000 cases |
| 07-11 | Architecture docs (ADR-015 D227/D228, ADR-003, kpi-contracts, ADR-009/016/017, brief) | 2 | none |
| 07-12 | Attribute all 56 survivors per file; kill every non-registry one (17 named + unattributed) | 4 | none |
| 07-13 | Remove @pending, PENDING_FLAGS, heavy_property marker and job-10 pin together, mutation gate incl. plan_job_registry.py | 2.5 | all 7 block in CI |

Scenario numbering follows the feature order (1 driven in full, 2 never entered from exit, 3 no retrace when a road leaves, 4 own leg and totals, 5 just before the End, 6 fewer retraces, 7 property).

The property's `heavy_property` marker and the `tests/ci` job-10 pin change together only at 07-13, and `@pending` is removed only there. 07-10 measures whether the marker is needed (3 s or more at profile ci); if not, 07-13 changes neither.

## 3. Golden order (D223): does it change?

Answer: no, and it is checked without re-blessing.

- I1 and I2 contain only Confirmed pairs that the road map answers. No arc is Unconfirmed, none is "no road", so no retrace arc exists. The weights apply only to Unconfirmed and retrace arcs; Confirmed arcs keep their plain metres with no scaling. D223's re-bless trigger "weighting mode" is therefore not met (07-04 states this link); two-phase weighting would meet it. The solver is handed a byte-identical cost matrix and runs the same single search, so it returns the same order.
- Check: 07-01 records, on the unchanged code, the sha256 of the cost matrix for I1 and I2 and commits it as a pin. Every later step keeps the pin and `pytest -m golden_order` green. `bless` is never run, and 07-13 requires an empty diff of `fixtures/golden/`.
- If the pin or the golden fails, the crafter stops and reports; re-blessing is the user's decision in its own commit (D223 triggers: weighting mode, SOLVER_IDENTITY, default budget, ortools version).
- The two-phase weighting of ADR-016 section 4 would be a weighting-mode change; it is not built here (decision 8). I2 is not made sparse here (decision 9).

## 4. Open decisions

Each has a recommended option, which the roadmap already applies. Overriding any of them changes the step named.

1. **Row text: structured fields or a rendered string?** Recommended: structured fields. The API row carries name "Retrace <track>", entry, exit, confidence, reason and real km/time; the sentence in the feature ("Retrace Colle del Sommeiller (Colle del Sommeiller -> Rochemolles) - Unconfirmed: ...") is composed by whoever displays it, as the scenarios already do (they compare coordinates and the reason). Consequence: no wording is stored, old runs stay readable, slices 08/09/11 reuse the same fields. Alternative (a stored rendered line) fixes the text in old runs and needs place names the planner does not hold. Step 07-06.
2. **Retrace as a `stops` row or a separate legs list?** Recommended: a row of the stops list, type `retrace`, directly after its track (ADR-017 section 3; the scenarios read "the next row"). Consequence: three places that assume one stop per item need care: the guard's each-item-once check (07-07), GPX export (07-09, it would otherwise fail) and the web list (07-09). K2/K3 diagnostics are unaffected (pinned in 07-06). Alternative (separate list) keeps the stops list clean but breaks the scenarios' "next row" reading and makes order across two lists the reader's problem.
3. **`retrace_sha256` definition.** Recommended: sha256 of the canonical points serialisation of the reversed point list of the same direction version, using the same serialiser as the canonical file (ADR-009 Amendment 2 wording). Computed by the job from the file it already reads, outside any lock. Consequence: one extra serialisation and hash per retraced track in the guard stage (information-only measurement at 07-13 against D230's 4.5 s for 20,000 points). Alternative (hash of the file's bytes reversed) is not a valid points file and cannot be compared with anything.
4. **Retrace duration and totals.** Recommended: the retrace is the track driven back, so its km and time are the track's own (length divided by the project's off-road speed), counted as off-road, matching the scenario "its 12.4 km and duration are included in the off-road totals". Road totals hold road legs only. Consequence: a retrace of 12.4 km adds 12.4 km to off-road totals and never the 10,000 m penalty. Alternative (road speed) would contradict FR-5.3 as amended.
5. **RULED (2026-11-10): accept as written, criterion 2 isolated in a 07-04 unit test; feature file unchanged. Original analysis follows.** Scenario 6 does not isolate criterion 2. "An order with fewer retraces wins over a shorter order" gives a Confirmed order (0 Unconfirmed legs) against retrace orders (at least 1), so criterion 1 decides, not "fewest retraces". Recommended: accept the scenario as written (it still proves a shorter retrace order never beats a longer Confirmed one) and isolate criterion 2 in a unit test in 07-04 (equal Unconfirmed counts, one order with a retrace, one with an Unconfirmed road leg 30 km longer). Option B, for the user and the acceptance designer, since the feature text is SSOT (D140) and I did not edit it: change the Given to "two dead-end trails can each be reached either with a retrace or by an order using an Unconfirmed road leg that is 30 km longer", and the title to match; the Then stays. Cost of B: the support step for this Given is rewritten (the Confirmed legs become one Unconfirmed leg) and the scenario still would not show criterion 1, which scenario 3 and the unit test cover. Recommended A because the unit test isolates the criterion more cheaply than rewriting an approved scenario.
6. **Where the unreachable item is named.** Recommended: one stored fact, `report.items` (the names, inside the existing JSON column, no migration), from which are composed the run detail's `messages` line, the job's ending message and (when slice 04 lands) the report row "Failed - unreachable". Wording follows US-08 S1: "Plan run #N failed: '<item>' cannot be connected to any other stop at any confidence level". Consequence: the OpenAPI snapshot gains the report field; old runs read back with no items. Alternative (message only) loses the structured fact slice 04 needs. Step 07-05.
7. **Dead-end exit coinciding with another item's point.** Recommended: identical points are connected at 0 m ("nothing to drive"), so no retrace is made; the sparse generator already leaves such exits out. Consequence: a track whose exit sits on a POI or another trail's entry is never a dead end, which matches the user's picture (the next stop is right there). Alternative (always require a road leg) would make a trail ending at its next stop need a retrace, which is wrong. Step 07-03.
8. **Weighting: single-phase now, two-phase later.** Recommended: one search with weights W1 > W2 > road metres (ADR-016 section 4 says both weightings honour the order). Keeps the golden. Consequence: on projects that do contain Unconfirmed or retrace arcs the search runs with very different arc sizes; quality at the 10,000 budget is measured on a sparse I2 variant at 07-04 (information, not a gate). Two-phase stays with 06a/06b, which re-bless then.
9. **I2 not made sparse in 03b.** Recommended: leave I2 as is; the sparse I2 (dead ends, no-road pairs) arrives with 06a/06b and their re-bless (06-01 said so). Consequence: no golden covers a retrace on the Pi; the Pi gate is not re-run for 03b unless the pin trips. Alternative (add a sparse I3 now) costs a new fixture, a bless and a Pi run for no 03b scenario.
10. **Fingerprint scheme fp1 to fp2.** Recommended: bump, as `fingerprint.py` says a later scheme that adds inputs must. Consequence: existing projects recalculate once instead of reusing a stored order. The golden uses `ignore_memo` and is unaffected.
11. **Retrace rule per arc or per exit.** Recommended: per arc (ADR-017): a retrace arc to a successor exists only where no road at any level goes from the exit to that successor. It is equivalent in effect to the brief's "only when no road leaves the exit" because an arc that has a road always beats a retrace on the ordering. Alternative (whole-exit rule) would declare a trail unreachable whenever its exit has a road to some unrelated stop but not to the one needed.
12. **Export of a retraced plan: SUPERSEDED by user ruling 1 (2026-11-10).** 07-09 writes the retrace as its own leg (kind `retrace`, the track's points reversed, name ending "[UNCONFIRMED - retraces the trail backwards; check it is drivable in reverse]") and marks every Unconfirmed leg, retrace or road, "[UNCONFIRMED - <reason>]". No 422, no waiver. The leg after a retrace starts at the track's entry. Slice 11 keeps the report and the rest and should find its "marked in the file" scenario already satisfied for names.
13. **Also carry `leg_reason`.** Recommended: yes, small. The reader parses the reason anyway and the guard must compare it (ADR-009 check 5); slice 08 needs it. Costs one field.
14. **Browser itinerary row in this slice.** Recommended: minimal row and "Unconfirmed" marks in 07-09 (otherwise the new row type shows blank). Map and warnings stay out. Could move to slice 12 if you prefer; then the retrace row is blank in the list until then.
15. **Ordering, third criterion: RULED (2026-11-10) road km only.** Retrace km are reported and counted off-road, not in the objective. Consequences: ADR-016/017 are amended in 07-11 (they say road + retrace km with a RETRACE_PENALTY tie-break); RETRACE_PENALTY is dropped because W2 already makes fewer retraces win; two plans with equal counts that retrace different tracks tie and either may win; the 07-04 brute-force property and the 07-08 objective use road metres only.
16. **Counting second-pass pairs.** Recommended: added to the job's legs total once, before solving; the poll's total may grow once. Alternative (a separate counter) keeps the total stable but adds a field.
17. **Estimate: accepted (ruling 4, all 13 steps).** 43 h against 6.4-8 h.
18. **NEW, for the user to accept: single-phase weighting risk.** On projects with Unconfirmed or retrace arcs, one GLS search over arcs of very different size may give longer road km than a two-phase search would at the 10,000 budget; the counts of Unconfirmed legs and retraces stay strict. Mitigation: 07-04 adds a real-child property over sparse models of at most 12 items (counts vs brute force, km gap reported) and times a sparse I2 variant. If you refuse the risk, two-phase must be built (a larger step, and a golden re-bless trigger).
19. **NEW: registry mutation cost.** 07-08 edits `plan_job_registry.py`, so 07-13's local mutation run includes it (budget 60-90 minutes); the 32 old registry survivors stay deferred, new survivors on 07-08's lines are killed in 07-12.
20. **NEW: survivor accounting.** The evidence names 49 of 56 survivors (32 registry, 9 diagnostics_service, 4 plan_request_job, 2 fingerprint_memo, 1 run_messages, 1 plan_run_queries); 7 are unattributed. 07-12 starts by re-running mutation to attribute all 56 and kills every non-registry survivor; the registry's are deferred; the two sets sum to the table's total.
21. **Boilerplate.** The repeated batch-2 and test-paradigm text is stated once at phase level; the step notes still contain phase 06's copies (editing 13 copies by hand risked the JSON), which is harmless.

## 5. Carry-overs: where each landed

| Carry-over | Decision |
|---|---|
| 56 mutation survivors (D224 context) | Named: 49 (registry about 32, diagnostics_service 9, plan_request_job 4, fingerprint_memo 2, run_messages 1, plan_run_queries 1); 7 unattributed. 07-12 attributes all 56 and kills every non-registry survivor (17 named + the unattributed ones outside the registry); the registry's (32 + any unattributed there) are deferred: slice 03b does not touch its state machine, the gate was met at 96.1 percent, its mutants are timing-bound (each timed-out mutant about 30 s, D224) and its tests were flaky under mutmut once; they belong to the mutation phase D224 names. |
| D227 ADR-015 table of endings (and D228) | 07-11, architect, after the code. |
| UI-DELIVER-7 (1) `#/diagnostics` vs ADR-003 and kpi-contracts | 07-11. |
| UI-DELIVER-7 (2) K2 warning banner not built | Deferred to slice 12 (UI foundation): it needs an acknowledgement state; recorded in 07-11. |
| UI-DELIVER-7 (3) leg cache in memory | Already slice 05's; noted in 07-11. |
| UI-DELIVER-7 (4) `run_messages.py` docstring says run time counts from job start | Fixed in 07-05, which edits that file. |

## 6. Answers to the crafter's open questions (summary)

- Row text: structured fields (decision 1). Retrace is a stops row (2). `retrace_sha256` (3). Duration and totals (4). Scenario 6 (5): accept and cover criterion 2 in a unit test; text change offered as option B only. Unreachable item named in `report.items` and composed into messages (6). Exit coinciding with another point: connected at 0 m, no retrace (7).
- Not open: the retrace is decided from the leg table by one rule that the model, the assembler and the guard share (07-03), so the solver's answer stays a plain list of item ids and the solver child's protocol does not change.

## 7. Risks to know before approving

- CI job 8 (mutation) will start on the pushed range, which touches domain and application files, and may be cancelled at 75 minutes as in D224; the local `make mutate BASE=<start>` at 07-13 is the evidence.
- Slow-properties is the busiest job after D231; 07-13 projects it from a local timing before the marker is set.
- Three components assumed one stop per item (guard, GPX builder, web list); each has a step. Any other consumer found during delivery is reported, not silently patched.
- The pin of 07-01 is the tripwire for everything D223 worries about; it must be recorded on the unchanged tip.
