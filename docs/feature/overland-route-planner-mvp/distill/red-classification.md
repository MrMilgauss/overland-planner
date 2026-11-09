# RED classification — slices 00b + 01a (pre-DELIVER fail-for-the-right-reason gate)

Feature `overland-route-planner-mvp` | DISTILL Revision 2 (final-gate fix round), 2026-11-02 | Host: dev-mac (macOS arm64, Python 3.12.13, no Docker). Data folders under `<repo>/.data/acceptance/` (never the OS temp folder, D182), removed after each test.

Runs:

```
uv run pytest -q tests
  -> 219 collected, 1 failed (the walking skeleton), 218 skipped, 0 errors

uv run pytest -q tests --run-pending=slice-00b --run-pending=slice-01a
  -> 28 failed, 191 skipped, 0 errors
     (00b + 01a + WS = 33 cases: 28 failed RED, 5 skipped @requires_external)
```

Classes: `MISSING_FUNCTIONALITY` = an assertion fires because the behaviour is not built (correct RED). No case is `IMPORT_ERROR`, `FIXTURE_BROKEN`, `SETUP_FAILURE`, `WRONG_ASSERTION` or `OBSERVABLE_NOT_AT_PORT`. Every failure is an `AssertionError`.

| # | Scenario (case) | Slice | Result | Class | Where it fails and why |
|---|---|---|---|---|---|
| 1 | WS: Marco starts his planner, loads his Assietta trail and still finds it after a restart | 01a | FAIL | MISSING_FUNCTIONALITY | Given "Marco's planner is running on his home server ...": the real `uvicorn --factory` process exits 1; stderr ends with `AssertionError: Not yet implemented -- RED scaffold: create_app` |
| 2 | Each start of the planner reports healthy and records one start-up line | 00b | FAIL | MISSING_FUNCTIONALITY | Same Given, same cause (server process exits on the scaffold) |
| 3 | Household members are asked for the shared password when it is switched on | 00b | FAIL | MISSING_FUNCTIONALITY | Given "the shared household password is switched on": `create_app` scaffold |
| 4 | A wrong shared password is refused | 00b | FAIL | MISSING_FUNCTIONALITY | Same |
| 5 | The planner stays on the home network by default | 00b | FAIL | MISSING_FUNCTIONALITY | When "checks what the set-up opens": `deploy/compose.yaml` is not delivered yet (slice 00b deliverable) |
| 6 | Marco creates a trip project | 01a | FAIL | MISSING_FUNCTIONALITY | Given "the planner is running": `create_app` scaffold |
| 7-8 | A project without a name is not created [an empty name] [a name of only spaces] | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 9 | A trip project survives a restart | 01a | FAIL | MISSING_FUNCTIONALITY | Given "Marco has created the project": `create_app` scaffold |
| 10 | Missing persistent storage is reported instead of losing projects silently | 01a | FAIL | MISSING_FUNCTIONALITY | Given "started on a data folder that would not survive a restart" (`FakeMountTable.with_mount(..., "overlay")`): `create_app` scaffold |
| 11 | A data folder the planner cannot write to stops it at start-up | 01a | FAIL | MISSING_FUNCTIONALITY | Then "the planner refuses to start": the process exits non-zero but logs no `health.startup.refused` line (0 found). Since D190 the exit code alone no longer passes this step |
| 12 | An older planner refuses data saved by a newer version instead of changing it | 01a | FAIL | MISSING_FUNCTIONALITY | Given "data folder holds 'Dolomiti 2028' saved by a newer planner version": the real planner must create the data first (waiver W3) and its process exits on the scaffold. The Alembic stub/stamp code runs only once the planner and `migrations/` exist |
| 12b | Data refused by an older planner is intact when Marco goes back to the newer one (re-review N-02) | 01a | FAIL | MISSING_FUNCTIONALITY | Same Given as #12 (the real planner must create the data first); its When "Marco goes back to the newer planner" restarts the newer version and its Then compares the project list through the HTTP API |
| 13 | Marco imports his Assietta trail | 01a | FAIL | MISSING_FUNCTIONALITY | Given "Marco has created the project": `create_app` scaffold |
| 14-15 | A file that is not GPX is rejected [notes.gpx] [empty.gpx] | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 16 | A trail file without any usable track is rejected | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 17 | A trail file that tries to read other files on the planner is rejected | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 18 | A trail file above the upload limit is refused | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 19 | Marco adds Briancon by coordinates | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 20-23 | Coordinates out of range are rejected with a reason (4 cases) | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 24-25 | Coordinates on the edge of the valid range are accepted (2 cases) | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 26 | Home is both Start and End of a round trip | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 27 | A one-way trip has a different Start and End | 01a | FAIL | MISSING_FUNCTIONALITY | Same |
| 28 | Marco brings the planner up on his Pi with one command | 00b | SKIPPED | n/a (`@requires_external @pi`) | Runs `up -d --force-recreate planner` on pi-host over ssh; only with `--run-external` at a start time the user names |
| 29 | The same setup runs on Marco's PC | 00b | SKIPPED | n/a (`@pc_amd64`) | Needs Docker on amd64 |
| 30 | Sharing the packaged planner never shares Marco's password | 00b | SKIPPED | n/a (`@docker @security`) | CI job 7 (`--run-external -m "compose or security"`, D170) |
| 31 | The idle planner leaves room on the Pi | 00b | SKIPPED | n/a (`@pi @kpi G1`) | `--run-external` on the Pi after 10 min idle |
| 32 | The packaged planner started without its data storage reports that projects would be lost | 01a | SKIPPED | n/a (`@compose`) | CI job 7 with `PLANNER_IMAGE` |

Why the in-process cases fail in a Given: they build the planner through the production composition root (Pillar 3), so until `create_app` exists the first step needing the planner fails with the scaffold's AssertionError. After DELIVER replaces the scaffold, each scenario fails on its own Then until its behaviour is built (one at a time, removing `@pending`). Assertions that will then apply: error envelope and enumerated code per status (D183), anchor enum `start / end / start_end`, state-delta on `projects.names` / `project.items`.

Static binding check (scratch script): every step line of `walking-skeleton.feature`, `slice-00b-planner-on-the-pi.feature` and `slice-01a-skeleton-items-on-pi.feature`, outlines expanded, matches exactly one step definition (0 unbound, 0 ambiguous), including the 5 skipped `@requires_external` scenarios.

Later slices (02-11) and the routing-port contract suite (steps module arrives at slice 06a, D194): collected and skipped as `pending: slice_NN not enabled yet`. No step definitions yet by design; do not run them with `--run-pending`.

## Slice 01b (DISTILL of 2026-11-04)

Host: dev-mac. Steps: `steps/plan_steps.py`, `steps/browser.py`, `tests/e2e/first-plan.spec.ts`. No RED scaffold: everything goes through HTTP or the browser, and the plan routes answer 404 until DELIVER builds them.

```
uv run pytest -q tests/acceptance/overland_route_planner_mvp --run-pending=slice-01b -k test_slice_01b
  -> 9 failed, 1 skipped (@manual), 196 deselected, 0 errors
```

| # | Scenario | Result | Class | Where it fails and why |
|---|---|---|---|---|
| 1 | Marco gets a first ordered itinerary | FAIL | MISSING_FUNCTIONALITY | When "presses Calculate": `the plan runs did not open: 404 {"code":"not_found","message":"Not Found"}` |
| 2 | Even the first plan drives the trail the way it was recorded | FAIL | MISSING_FUNCTIONALITY | Given "has pressed Calculate": same 404 |
| 3 | Marco downloads the first plan as a standard GPX file | FAIL | MISSING_FUNCTIONALITY | Given "plan run #1 ... exists": same 404 |
| 4 | The first plan opens in OsmAnd | SKIPPED | n/a (`@manual`) | Evidence by hand (docs/demo/) |
| 5 | A one-way trip ends at its End | FAIL | MISSING_FUNCTIONALITY | When "presses Calculate": same 404 |
| 6 | A trail that starts at the Start place is reached by a zero-length leg | FAIL | MISSING_FUNCTIONALITY | When "presses Calculate": same 404 |
| 7 | A plan still being worked out cannot be exported yet | FAIL | MISSING_FUNCTIONALITY | Given "still being worked out": same 404 |
| 8 | Plans are refused while the optimizer cannot start | FAIL | MISSING_FUNCTIONALITY | When "presses Calculate": same 404 |
| 9 | A second Calculate while a plan is being worked out is refused | FAIL | MISSING_FUNCTIONALITY | Given "still being worked out": same 404 |
| 10 | Marco plans the Assietta day trip in his browser | FAIL | MISSING_FUNCTIONALITY | When "presses Export GPX": Playwright `locator.click: Timeout 15000ms exceeded` waiting for the button "Calculate", which the page does not have yet |

Every failure is an `AssertionError`; the Givens that use only slice 01a behaviour pass. Because RED stops at the first missing route, the Then steps were also run once against a throwaway stand-in for the plan routes (not committed): scenarios 1-3 and 5-9 passed against a correct stand-in, and failed on the expected assertion for a reversed trail, a wrong order, a missing refusal, a second job, an early plan run id, GPX extensions and a wrong file name. The Then steps of scenario 10 have not run yet.

## Slice 02 (DISTILL of 2026-11-08)

Host: dev-mac (macOS 26.2 arm64, Python 3.12.13, OR-Tools 9.15). Steps: `steps/direction_steps.py` (all 18 scenarios), `steps/in_memory_planning.py` (layer 1-2 composition and generated projects for the `@property` scenarios, D192), `steps/browser.py` (`PhoneItineraryJourney`), `tests/e2e/phone-itinerary.spec.ts` (chromium at a 390 px viewport, no real device). Doubles: `RuleBreakingTourSolver` (waiver W1) and `InProcessOrToolsTourSolver` (the child's own solve in the test process; not a waiver) in `tests/common/solver_fakes.py`. Fixtures, synthetic (D198; `~/Downloads/assietta.gpx` not used): `fixtures/gpx/jafferau-loop.gpx` (18.9 km loop from and to Bardonecchia, recorded clockwise), `fixtures/gpx/maira-varaita-ridge.gpx` (69.5 km), scripted road map `fixtures/road-maps/plan-run-4.yaml` (trip legs 86.1 + 168.2 + 172.4 + 185.6 = 612.3 km, 9h40). Binding `test_slice_02.py` (slice 02 left `test_pending_slices.py`); the feature keeps `@slice-02 @pending`; the only feature edit is `@slow` on the A-6 property (D216). No RED scaffold, nothing under `src/` or `migrations/` changed.

```
uv run pytest -q tests/acceptance/overland_route_planner_mvp --run-pending=slice-02 -k test_slice_02
  -> 15 failed, 5 passed, 186 deselected, 0 errors, 23 s (Hypothesis profile dev)
uv run pytest -q tests/acceptance/overland_route_planner_mvp --run-pending=slice-02 -k test_slice_02 -m "not slow and not solver_child"
  -> 7 failed, 3 passed, 196 deselected, 18 s   (what pre-push will run once @pending goes)
uv run pytest -q tests -m "not slow and not solver_child"
  -> 460 passed, 171 skipped, 48 deselected, 0 failed, 106 s
uv run pytest -q tests/acceptance -m "solver_child and not slice_02"
  -> 9 passed, 3 skipped (01b unchanged by the shared-step edits)
```

Static binding check (scratch script over pytest-bdd's step registry): 80 step lines of `slice-02-directional-optimizer.feature`, outlines expanded, each match exactly one definition (0 unbound, 0 ambiguous); 01b, 01a, 00b and the WS re-checked, still 0/0.

| # | Scenario (case) | Result | Class | Where it fails and why |
|---|---|---|---|---|
| 1 | The Assietta is driven from Pian dell'Alpe to Sestriere even when reversing would be shorter | PASS | ALREADY_GREEN | Slice 01b's directional node and anchors already give it: the row's places are checked by coordinates (D109), legs 21.79 + 21.79 km |
| 2 | No generated plan ever drives a track in reverse (`@property`) | PASS | ALREADY_GREEN | Layer 1-2: 100 cases (dev) in 4.4 s, 1,000 (ci) in 45 s; guard as oracle plus the test's own reading of the stored files |
| 3 | Tracks are always driven in full (`@property`) | PASS | ALREADY_GREEN | dev 4.5 s, ci 51 s |
| 4 | A loop trail is driven in its recorded order | PASS | ALREADY_GREEN | The exported plan holds the Jafferau loop's 81 points in recorded order |
| 5 | A plan that would break a hard rule is never shown | FAIL | MISSING_FUNCTIONALITY | Then "its consideration report keeps the reason": the Failed run #2 has no `report`; it stores only the code `internal_invariant_violation` (D206: mapping to product words is DELIVER work). Its first and last Thens (not shown, Failed, run #1 stays the latest success) already pass |
| 6 | The trip always starts at Start and ends at End (`@property`) | PASS | ALREADY_GREEN | dev 5.4 s, ci 54 s (both Thens share each project's plan) |
| 7-8 | Calculate is refused while an anchor is missing [Start] [End] | FAIL | MISSING_FUNCTIONALITY | Given "has no Start/End": removing the anchor place, `DELETE .../items/{item_id}`, answers 404 (no route) |
| 9 | Only POIs can be chosen as Start or End | FAIL | MISSING_FUNCTIONALITY | Then "Strada dell'Assietta is not offered": `GET .../items?type=poi` ignores `type` and lists the track |
| 10 | A track cannot be made the Start even when asked directly | FAIL | MISSING_FUNCTIONALITY | Then he sees: Marco saw "Invalid request - end_item_id: Input should be a valid string" (no End yet, and the anchors cannot leave one unset); the slice 01b text is also "Only a place of this project can be the Start or End", not the scenario's |
| 11 | Removing the Start POI clears the Start | FAIL | MISSING_FUNCTIONALITY | Then "the project has no Start and no End": the removal answers 404. The new Given "Marco has pressed Calculate" (D217) already computes a ready plan run first; "the plan is marked Stale" checks that run, by id, not by number |
| 12 | A trip with only a Start and an End is a direct road route | FAIL | MISSING_FUNCTIONALITY | Then "the totals show that road leg": plan run #1 has no `totals`. The itinerary Then (two stops, one leg as the offline road map gives it) already passes |
| 13 | Identical inputs produce identical plans (`@solver_child`, real restart) | FAIL | MISSING_FUNCTIONALITY | Then: no `totals`; order and legs of runs #1-#3 were read and agree |
| 14 | Any project planned twice from scratch gets the same plan (`@property @slow`) | FAIL | MISSING_FUNCTIONALITY | First pinned example: "the plan run has no totals" (1 s) |
| 15 | Totals separate road and off-road driving | FAIL | MISSING_FUNCTIONALITY | Then "the totals show road 612.3 km ...": plan run #4 has no `totals`. Next in line: the road map ignores `MOCK_PLAN`, so the road km would be the straight-line ones |
| 16 | The itinerary shows each stop with legs and cumulative distance | FAIL | MISSING_FUNCTIONALITY | Then row 2: leg 65.98 km, not 86.1 km: the scripted road map (`MOCK_PLAN`) is not read. Then `cumulative_km`, `track_km`, `offroad_s` |
| 17 | The off-road speed setting changes track durations | FAIL | MISSING_FUNCTIONALITY | Given "has off-road speed 12 km/h": `PATCH /api/projects/{id}` answers 404 |
| 18-19 | An off-road speed that cannot be driven is refused [0] [-5] | FAIL | MISSING_FUNCTIONALITY | Given "has off-road speed 15 km/h": same 404 |
| 20 | Giulia reads the itinerary on her phone (`@ui @phone`) | FAIL | MISSING_FUNCTIONALITY | Then: the browser ran (real server, chromium at 390 px); page width and every itinerary row fit the screen already; fails on "plan run #4 shows no totals" (the page shows no element labelled "Totals" either) |

Every failure is an `AssertionError` reached through a driving port; none is `IMPORT_ERROR`, `FIXTURE_BROKEN`, `SETUP_FAILURE`, `WRONG_ASSERTION` or `OBSERVABLE_NOT_AT_PORT`.

**ALREADY_GREEN (5 cases) and how each Then was shown to fail.** A throwaway pytest plugin (not committed; it monkeypatches the planner in the test process, `src/` untouched) applied one mutation per run:

| Mutation (guard switched off where noted) | Fails | On |
|---|---|---|
| every track stop driven exit -> entry (guard off) | #1, #2, #3 | #1 "the itinerary row reads": entered 16,762 m from Pian dell'Alpe; #2 "assietta is driven (44.958, 6.879) -> (45.056, 7.041)"; #3 "assietta is cut short" |
| every road leg 3 km longer (guard off) | #1 | "the plan has about 43.6 km": a leg is 24.79 km |
| every track stop names one point fewer (guard off) | #3 | "not driven with all its 601 stored points" |
| the Start put second (guard off) | #6 (first Then), #1 | "the trip starts at item-2" |
| the End put second to last (guard off) | #6 (second Then) | "the trip ends at item-0" (the first Then passed) |
| the export writes each trail's points reversed | #4 | "'Jafferau loop' is not driven in its recorded order (81 points)" |
| A-6 with a totals stand-in | #14 passes | dev, 100 cases x 2 solves at budget 10,000: 248 s |
| the same stand-in, order by chance (guard off) | #14 | "the order differs" |

With the guard off, the properties still fail: their oracle is the guard re-run on the stored plan plus the test's own reading of the canonical files, so a broken guard does not hide a broken plan.

**Markers and timings** (D199 precedent, decided per scenario in `test_slice_02.py`): `solver_child` on every scenario that runs a real solve in the solver child or a browser (#1, #4, #5, #11 since D217, #12, #15, #16, #17, #20, plus #13 tagged in the feature); each takes 0.4-1.1 s here (the browser one 3.9 s), but they belong to CI job 2 like 01b's. The three properties #2, #3, #6 have no child (in-process solve) and stay in pre-push: 15 s together with profile dev; CI profile ci: 2 min 30 s for the three. #14 is `@slow` (D216): about 4 min in dev with a stand-in, so about 8 min at ci's 200 cases on the Mac; it needs its own CI job. The refusals and settings scenarios (#7-10, #18-19) never reach a solve and run in pre-push (0.2-0.3 s each).

**Open points for DELIVER / the PO** (not resolved by changing scenario text):
- #5: the `TourSolver` port's order names item ids and a track has one node with no reversed variant (HC-1, D45), so "proposes an order that drives the Assietta from Sestriere to Pian dell'Alpe" cannot be said through the port. W1's double names a node the model never offered (`reversed:<track id>`) in the track's place; the guard refuses it as HC-3 (extra/missing item), not HC-1.
- #11: resolved by D217 (2026-11-08): the scenario gains "And Marco has pressed Calculate" before the removal, so "the plan is marked Stale" has a run to mark; it is a branch fixture, so the Then finds that run by id and asserts no number. #11 now runs a real solve and is `solver_child`.
- #4: Calculate needs a Start and an End; the scenario names neither, so the Given also makes Casa Marco Start and End.
- #7-8: "has no Start/End" is bound as "had both, then removed the place that was the missing one" (US-04 S4's action), so the refusal must name the missing anchor even when the other one is set.
- #10: "tries to set X as Start" keeps the End as it is (none here), so the anchors must accept an unset End.
- The Thens of the RED scenarios have not run against a stand-in yet; each stops at its first missing piece.

## Slice 03 (DISTILL of 2026-11-09)

Host: dev-mac (macOS 26.2 arm64, Python 3.12.13, OR-Tools 9.15). Steps: `steps/performance_steps.py` (new; all 19 scenarios), plus small shared edits: `steps/planner.py` (`PlannerSession.stop_plan_job`, `.diagnostics`; `ServerPlanner.pid`, `.kill_abruptly`; `RemotePlanner` for the Pi), `steps/world.py` (`shutdown` also ends scripted children), `steps/plan_steps.py` (`note_plan_texts`: a poll payload's or Calculate answer's `message` and `notices`, and a run's `messages`, become what Marco has seen), `steps/direction_steps.py` (`"X" is offered` no longer matches "Re-optimise ...", which is slice 03's), `conftest.py` (registers the new module). Binding `test_slice_03.py`; slice 03 left `test_pending_slices.py`. The feature is unchanged and keeps `@slice-03 @pending`. No RED scaffold; nothing under `src/`, `migrations/` or `web/src` changed.

Doubles (waiver W1, `tests/common/solver_fakes.py`): `ScriptedTourSolver` is the production `OrToolsTourSolver` parent (spawn, pipe, safety bound, whatever slice 03 adds to `solve`) with a scripted child (`scripted_tour_child`, picklable, no OR-Tools): `improving` (two valid incumbents, the second better, then silence without a final), `silent` (never a valid route), `no_route` (`(FINAL, None)` at once), `finish` (incumbents then the final order). The child logs its pid and the item ids of each incumbent to a JSON-lines file, so the scenario knows the best route so far and can SIGKILL the child ("the optimizer stops abnormally"). The incumbent message `("incumbent", node_order, objective)` is DISTILL's proposal; DELIVER aligns the tag with `tour_child`. `FollowingClock` (a `FakeClock` that follows real time) is used wherever limits run, so a limit measured on the `Clock` port and one measured on the wall clock both elapse.

60-item project: a test-side deterministic builder (`synthetic_trip`, seed 20261109: 40 three-point trails "Pista 01-40" and 20 places "Punto 01-20" in the Western Alps, Start "Casa Marco, Torino", End "Briancon", 62 stops; 65 items = 45 trails + 20 places), imported through the API. Chosen for every scenario where the solver is scripted or the exact project does not matter: the scripted child derives its orders from the model, and the real-solve scenarios (#4, #5, #16-18) only need a 60/65-item project. Only #1, #3 (Pi) and #6 (golden order) read the committed reference project.

Fixture contract proposed for slice 03-ops (the Givens fail with a clear AssertionError while it is missing):
- `tests/acceptance/overland_route_planner_mvp/fixtures/golden/i1-dense.json` (and `i2-sparse.json`): `{name, seed: 20261101, generator, solver_budget, start: {name, lat, lon}, end: {name, lat, lon}, tracks: [{name, points: [[lat, lon, ele], ...]}], pois: [{name, lat, lon}], road_map: <optional MOCK_PLAN file next to it, for I2's missing pairs>, expected_order: [stop names, Start first, End last], expected_order_sha256}`. Hash: sha256 of the stop names joined by `\n`, UTF-8 (to align with the CI job 3 golden check and findings.md Setup if 03-ops defines it otherwise). The steps build each GPX file from `points` and import it through the API.
- `fixtures/golden/i1-dense.reference-30min.json`: `{road_km, order, search_s: 1800, host, solver_identity}` (the 30-minute PC search).
- The Pi scenarios reach `planner-perf` through `PLANNER_PERF_URL` (set by `make perf-pi`), seed I1 as a `__perf <timestamp>` project (outside K1/K7), read `stage_ms.solve` from each finished poll payload.

API shapes the steps ask for (DISTILL's proposal; brief §5 field table, §8 run flags): poll payload `incumbent`, `legs_new`, `legs_cached`, `stage_ms`, `message`, `notices`; Stop `POST /api/plan-jobs/{id}/stop` (200 + payload, D136); plan run detail `not_fully_optimised` (`time_limit` | `stopped` | `optimizer_failed`; the step maps each "not fully optimised (...)" label to its code), `memo_hit` (Re-optimise is offered exactly on a reused plan), `messages` ("Planned 60 items in <run time>", "Reused the identical plan of run #N", "stopped before a valid route was found"); limits `FEASIBILITY_LIMIT_S` / `OPTIMISATION_LIMIT_S`; `GET /api/diagnostics[?project_id=]` with `k5.stage_p95_s`, `k5.retried_jobs`, `retried_jobs_30d`, `jobs_by_terminal_state_30d`, `k7.runs_per_project_day.max`, `k2.invariant_violations`, `k3.report_omissions` (kpi-contracts.yaml). The look-up latency of the offline road map is a proposed `MOCK_PLAN` key `latency: {answered_at_once_pairs, then_each_call_s}`, written per test to `tmp_path`.

```
uv run pytest -q tests/acceptance/overland_route_planner_mvp --run-pending=slice-03 -k test_slice_03
  -> 14 failed, 3 passed, 2 skipped, 187 deselected, 0 errors, 104 s
uv run pytest -q tests -m "not slow"
  -> 567 passed, 165 skipped, 1 deselected, 0 failed, 166 s
uv run ruff check tests ; uv run ruff format --check tests
  -> All checks passed ; 125 files already formatted
```

Static binding check (scratch script over pytest-bdd's step registry): 79 step lines of `slice-03-pi-performance.feature`, each matches exactly one definition (0 unbound, 0 ambiguous); slice 02 re-checked (only its outline placeholders, as before).

| # | Scenario | Result | Class | Where it fails and why | Local s | Markers |
|---|---|---|---|---|---|---|
| 1 | The solve stage for 60 items fits the budget on the Pi | SKIP | SKIPPED | `@requires_external @pi`: make perf-pi only (D96); would also stop at the missing I1 fixture | est. 10-12 min on the Pi (warm-up + 10 runs) | feature tags |
| 2 | The best plan found is returned when the optimisation limit is reached | FAIL | MISSING_FUNCTIONALITY | Then "a complete plan is shown within 25 seconds": plan run #1 is Failed `optimizer_failed`: the parent takes the first incumbent message for the end of the child (no incumbent streaming, no limits) | 2.4 (green est. 21) | solver_child; slow recommended |
| 3 | A plan found on the Pi is nearly as good as a long search | SKIP | SKIPPED | `@requires_external @pi`; needs I1 and its 30-minute reference | est. 1-2 min on the Pi | feature tags |
| 4 | Marco sees how long planning took | FAIL | MISSING_FUNCTIONALITY | Then: the results show no "Planned 60 items in" (no `messages` on the run, nothing in the poll) | 2.0 | solver_child |
| 5 | A project above 60 items is planned with a notice that it may take longer | FAIL | MISSING_FUNCTIONALITY | Then he sees "Large project - ...": Marco saw nothing. With the notice injected as a stand-in, "the plan is calculated" passes (65 items, 67 stops) | 1.8 | solver_child |
| 6 | The 60-item plan is the same on every machine | FAIL | MISSING_FUNCTIONALITY | Given: `fixtures/golden/i1-dense.json` does not exist (slice 03-ops). Stand-in: a throwaway I1 (the synthetic 60 items, a deliberately wrong expected order): the real solve at the default budget ran and the Then failed "the order differs from the golden order" | 0.1 (22.3 with the stand-in) | solver_child (feature); slow recommended |
| 7 | Marco stops a long optimisation and keeps the best route so far | FAIL | MISSING_FUNCTIONALITY | Given "a valid route has been found": no incumbent is reported while optimising; the job ends Failed `optimizer_failed` (same cause as #2) | 2.4 | solver_child |
| 8 | Stopping before any valid route fails the run with a reason | FAIL | MISSING_FUNCTIONALITY | Then: after Stop the job is still `solving` 15 s later: `POST /api/plan-jobs/{id}/stop` does not exist | 15.3 (green est. 3) | solver_child |
| 9 | Stopping while roads are still being looked up changes nothing | FAIL | MISSING_FUNCTIONALITY | Given: the planner refuses to start with the road map's `latency` key (offline road-map latency is planned for 06a) | 0.3 (green est. 3) | none (never solves) |
| 10 | No valid route within the feasibility limit | FAIL | MISSING_FUNCTIONALITY | Then: the job is still `solving` after 45 s: `FEASIBILITY_LIMIT_S` is not read, only the 600 s safety bound applies | 45.3 (green est. 31) | solver_child; slow recommended |
| 11 | The optimizer ends without any route | PASS | ALREADY_GREEN | D122 already holds: `(FINAL, None)` gives Failed `no_valid_route_found` in 0.4 s, no stops, export 422 `validation_error` | 0.4 | solver_child |
| 12 | An optimizer that crashes after finding a route still gives the best route so far | FAIL | MISSING_FUNCTIONALITY | Given: as #7 | 2.4 | solver_child |
| 13 | The feasibility limit reached while roads are still being looked up changes nothing | FAIL | MISSING_FUNCTIONALITY | Given: as #9 | 0.3 (green est. 31) | none; slow recommended |
| 14 | A later no-change Recalculate returns the same plan as a stopped run | FAIL | MISSING_FUNCTIONALITY | Given (chains #7's Given + When + label): as #7 | 2.4 | solver_child |
| 15 | Re-optimise starts a fresh search | FAIL | MISSING_FUNCTIONALITY | Given (chains #14): as #7 | 2.4 | solver_child |
| 16 | Closing the planner during a long optimisation leaves nothing running | PASS | ALREADY_GREEN | Real uvicorn process, real OR-Tools child (budget 100,000,000), SIGKILL of the server: the child is gone within 3 s (pipe-EOF watchdog on macOS), no run after the restart | 5.0 | solver_child (feature) |
| 17 | Only one plan is calculated per project at a time | PASS | ALREADY_GREEN | Slice 01b's 409 `job_active` and its message; the 60-item job stays `solving` | 2.9 | solver_child |
| 18 | A plan for a second project waits for the optimizer and can be stopped while waiting | FAIL | MISSING_FUNCTIONALITY | Then: "Dolomiti 2028" still `waiting_for_optimizer` after Stop (the Given already passes: D133's slot exists); Stop missing | 16.0 (green est. 4) | solver_child |
| 19 | Marco's diagnostics show how planning went | FAIL | MISSING_FUNCTIONALITY | Then: `GET /api/diagnostics` answers 404 `not_found` (DV-3; `plan_job_log` deferred by D204) | 1.4 | solver_child |

Every failure is an `AssertionError` reached through a driving port; none is `IMPORT_ERROR`, `FIXTURE_BROKEN`, `SETUP_FAILURE`, `WRONG_ASSERTION` or `OBSERVABLE_NOT_AT_PORT`. Where RED stops in a Given (#6, #7, #9, #12-15), only #6's and #5's Thens could be run against a throwaway stand-in; the others need the production incumbent streaming or road-map latency to reach their Thens.

**ALREADY_GREEN (3) and how each was shown to fail** (throwaway edits of `performance_steps.py`, restored from a copy; `src/` untouched):

| Mutation | Fails | On |
|---|---|---|
| #11's optimizer finds a route after all (`finish` instead of `no_route`) | #11 | "fails with 'optimizer_failed'" (the reason check fires; today an incumbent message ends the child) |
| #16: a `sleep 20` process is counted among the optimizer processes | #16 | "optimizer processes still running 3 s after the planner stopped: [7682]" |
| #17: the 60-item solve child is killed and the job ends before the second press | #17 | "'A plan is already being calculated for this project' not shown; Marco saw []" |

#16's second Then ("no plan run after the restart") was not mutated separately.

**Markers and CI cost.** `solver_child` on every scenario that spawns a solve child (scripted or real) or a planner process. Four scenarios are long when green (#2 about 21 s, #6 22 s, #10 and #13 about 31 s each: the 20 s / 30 s limits are the scenario text, and #6 solves 60 items at budget 10,000) and should be `slow`; `slow` is not set because `tests/ci/test_ci_workflow.py::test_slow_properties_job_runs_a_6_and_the_hc_properties_at_profile_ci_and_job_2_does_not` pins the slow population to A-6 + the slice 02 HC properties (D221). Without them, slice 03 adds about 50 s to CI job 2 when enabled (13.6 of 15 min today).
