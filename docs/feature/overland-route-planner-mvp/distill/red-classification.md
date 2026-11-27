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

The second Then of #16 ("no plan run after the restart") was not mutated by the binding agent; the orchestrator showed it able to fail afterwards (a real plan run started after the restart made it fail with "the interrupted plan left a plan run"), and reverted the mutation.

**Markers and CI cost.** `solver_child` on every scenario that spawns a solve child (scripted or real) or a planner process. Four scenarios are long when green (#2 about 21 s, #6 22 s, #10 and #13 about 31 s each: the 20 s / 30 s limits are the scenario text, and #6 solves 60 items at budget 10,000) and should be `slow`; `slow` is not set because `tests/ci/test_ci_workflow.py::test_slow_properties_job_runs_a_6_and_the_hc_properties_at_profile_ci_and_job_2_does_not` pins the slow population to A-6 + the slice 02 HC properties (D221). Without them, slice 03 adds about 50 s to CI job 2 when enabled (13.6 of 15 min today).

## Slice 03b (DISTILL of 2026-11-10)

Host: dev-mac (macOS 26.2 arm64, Python 3.12.13, OR-Tools 9.15). Steps: `steps/retrace_steps.py` (new; all 7 scenarios). Small shared edits: `steps/places.py` (places Rochemolles, Colle del Sommeiller, Rifugio III Alpini; the two trail files in `TRAIL_FILES`), `steps/in_memory_planning.py` (`GeneratedProject.road_map_provider()`, default the plain offline road map; `InMemoryComposition` and `guard_finds_nothing` ask the project for it), `conftest.py` (registers the module). New data: `fixtures/gpx/colle-del-sommeiller.gpx` (Rochemolles -> Colle del Sommeiller, 12.4 km) and `fixtures/gpx/valle-stretta.gpx` (Bardonecchia -> Rifugio III Alpini, 9.6 km), synthetic (D198), 25 points each. Binding `test_slice_03b.py`; slice 03b left `test_pending_slices.py`. The feature is unchanged and keeps `@slice-03b @pending`. No RED scaffold; nothing under `src/`, `migrations/` or `web/src` changed.

Doubles: none new. The planner is the production app; the offline road map is scripted per pair through `MOCK_PLAN` (brief section 6 already lists "per-pair level (`confirmed`, `unconfirmed:<reason>`, `none`)"; the atdd policy lists "scripted per-pair levels"). The slice-02 `MOCK_PLAN` reader accepts only `{from, to, distance_m, duration_s}`, so a road map with levels is refused at start-up: that is the first RED of every scenario.

Proposed contract (DISTILL's proposal, DELIVER owns the shapes; the steps ask only for what the scenarios read):
- `MOCK_PLAN` pair: `{from: [lat, lon], to: [lat, lon], distance_m, duration_s, level}`; `level` absent or `confirmed` = Confirmed, `unconfirmed:<reason>` = an Unconfirmed leg (with distance and time), `none` = no road at any level (no distance or time). Unlisted pairs keep straight line x 1.3, Confirmed.
- plan run stops: a retrace is its own row directly after its track: `type: "retrace"`, `name: "Retrace <track>"`, `entry` = where it starts (the track's exit), `exit` = where it ends (the track's entry), `track_km`/`offroad_s` = the real retrace km and time, `leg_km: null`, `confidence: "unconfirmed"`, `reason: "retraces the trail backwards; check it is drivable in reverse"`. The Gherkin's row text is composed from these fields and the place names (the steps compare coordinates and the reason, not a rendered string).
- every stop reached by road: `leg_confidence: "confirmed" | "unconfirmed"`.
- totals keep exactly the six slice 02 keys; `road_*` hold road legs only, `offroad_*` hold tracks and retraces; no penalty anywhere.
- an unreachable item: Failed run with `failure_reason: "unreachable"`, no stops, no totals, export 422; its report reason or the job message names the item.
- in memory (layer 1-2): `PlanStop.kind == "retrace"`, `item_id` = its track's, `entry`/`exit` as above.

```
uv run pytest tests/acceptance/overland_route_planner_mvp/test_slice_03b.py --run-pending=slice-03b -p no:cacheprovider
  -> 7 failed, 0 passed, 0 errors, 2 s (Hypothesis profile dev)
uv run pytest -q tests -p no:cacheprovider
  -> 668 passed, 149 skipped, 0 failed, 641 s (profile dev; the first run failed once on the CI pin test, see Markers)
uv run ruff check tests ; uv run ruff format --check tests
  -> All checks passed ; files already formatted
```

Static binding check (scratch script over pytest-bdd's step registry): the 27 distinct step lines of `slice-03b-out-and-back-retrace.feature` each match exactly one definition (0 unbound, 0 ambiguous); slices 00b, 01a, 01b, 02, 03 and the walking skeleton re-checked: 0 ambiguous (the unbound ones are the outline placeholders, as before).

| # | Scenario | Result | Class | Where it fails and why | Local s | Markers |
|---|---|---|---|---|---|---|
| 1 | A dead-end trail is driven in full and then retraced | FAIL | MISSING_FUNCTIONALITY | Given "no road leg leaves its exit ...": `AssertionError: the planner refused to start with the scripted road map (StartupRefusedError(1)): the offline road map does not read the per-pair level` (log: `pairs[0] must have exactly from, to, distance_m and duration_s`) | 0.3 | solver_child |
| 2 | A trail is never entered from its exit | FAIL | MISSING_FUNCTIONALITY | Given "track Valle Stretta whose entry cannot be reached ...": same | 0.2 | none (a Failed run at the reachability check, before any solve) |
| 3 | No retrace when a road leaves the exit | FAIL | MISSING_FUNCTIONALITY | Given "an Unconfirmed road leg leaves its exit ...": same (`unconfirmed:<reason>` level) | 0.2 | solver_child |
| 4 | A retrace is its own leg and counts as off-road driving | FAIL | MISSING_FUNCTIONALITY | Given "a plan of ... retraces ...": same (chains #1's Givens) | 0.2 | solver_child |
| 5 | A dead-end trail just before the End is retraced to reach the End | FAIL | MISSING_FUNCTIONALITY | Given "no road leg leaves its exit at any confidence level ...": same | 0.2 | solver_child |
| 6 | An order with fewer retraces wins over a shorter order | FAIL | MISSING_FUNCTIONALITY | Given "two dead-end trails ...": same (the Given first proves its own premise: the Confirmed order is 30 km longer than the best retrace order) | 0.3 | solver_child |
| 7 | No track item is ever driven backwards, retraces included | FAIL | MISSING_FUNCTIONALITY | Then "no track item is ever driven from exit to entry": the pinned readable examples (Sommeiller round trip, Sommeiller on the way to Briancon) fail first: `AssertionError: the offline road map does not read the per-pair level: none of slice 03b: ... pairs[0] must have exactly from, to, distance_m and duration_s` | 0.1 | `property` (feature tag); `heavy_property` recommended, not set (below) |

Every failure is an `AssertionError` reached through a driving port (the in-process planner's start-up for #1-#6, the layer 1-2 composition for #7); none is `IMPORT_ERROR`, `FIXTURE_BROKEN`, `SETUP_FAILURE`, `WRONG_ASSERTION` or `OBSERVABLE_NOT_AT_PORT`. No scenario is ALREADY_GREEN and none is skipped: every Given needs a road without a leg, an Unconfirmed leg or both.

**Because RED stops at the road map, the Thens were run against a throwaway stand-in** (a pytest plugin outside the repository that answered Calculate, the poll and the plan run from a hand-made plan built from the real catalog and the scripted road map, with MUT=<name> breaking it). Correct stand-in: #1-#6 pass. Each mutation below makes the named scenario fail on the named check (all reverted; the plugin is not committed):

| Mutation of the stand-in | Fails | On |
|---|---|---|
| the track row runs exit -> entry | #1, #3 | "Colle del Sommeiller is entered 12403 m from Rochemolles" |
| the retrace km carry the 10 km penalty | #1, #4 | "the retrace is 22.4 km, not 12.4 km" |
| the retrace row is after the next stop / missing | #1, #4, #5 | "the row after 'Colle del Sommeiller' is ..." / "the plan is [..]" |
| the road into the next stop starts at the exit (150 km, not 64 km) | #1, #4, #5 | "the road into Briancon is 150.0 km, not 64.0 km" |
| the retrace is not flagged Unconfirmed / carries a shorter reason | #1 | "the retrace is None, not Unconfirmed" / "the retrace says '...', not '...'" |
| totals gain a `retrace_km` key | #4 | "the totals show [..]: a retrace has no breakdown of its own" |
| road km include the retrace (+10) | #4 | "road is 132.0 km, not 122.0 km" |
| a retrace is planned although a road leaves the exit | #3 | "the plan retraces: ['Retrace Colle del Sommeiller']" |
| the Unconfirmed leg is not flagged / starts at the entry | #3 | "the road leg is 'confirmed'" / "the road into Casa Marco, Torino is 64.0 km, not 150.0 km" |
| the unreachable run names no item / has another reason / shows stops / is not Failed | #2 | "nothing Marco read names 'Valle Stretta'" / "plan run #1 fails with 'timeout'" / the stops and delta checks |
| the plan retraces both trails | #6 | "the plan is ['Casa Marco, Torino', 'Valle Stretta', 'Retrace Valle Stretta', ...]" |
| the scripted Confirmed order is 33 km longer (not 30) | #6 | Given: "the scripted Confirmed order is 155.0 km, the retrace order 122.0 km: not 30 km longer" |

The property's two oracles (`retraced_tracks`, `reversed_track_stops`) were run on hand-made plans: a reversed track, a retrace before its track, a retrace of another item and a retrace entry -> exit instead of exit -> entry each fail; a missing retrace fails the second Then (retraced tracks must equal the dead-end tracks driven).

**Markers and CI cost.** `solver_child` on #1, #3-#6 (a real OR-Tools child per Calculate; each about 2 s when green). #2 stays in pre-push (no solve). #7 solves in-process and is `heavy_property` (D221): a stand-in run of the same generator and solve (without retrace arcs, which the planner cannot plan yet) took 0.9 s for 100 cases (profile dev) and 7.5 s for 1,000 cases (profile ci) of planning alone, so it is above the 3 s line at ci and should be `heavy_property`. The marker is not set: `tests/ci/test_ci_workflow.py::test_slow_properties_job_runs_the_slow_and_heavy_scenarios_at_profile_ci_and_job_2_does_not` pins job 10's population by name (it failed once the marker was set), so the orchestrator sets the marker and adds the test to that pin together before slice 03b is enabled. At profile dev it stays in pre-push. Re-measure once retrace arcs exist.

## Slice 12c (`slice-12c-the-planner-knows-its-map.feature`), DISTILL D312 (revised after the consolidated review), 2026-11-26

Host: dev-mac (macOS arm64, Python 3.12). Production code for the slice does not exist; the step bindings import none, so nothing can be an `IMPORT_ERROR`.

```
uv run pytest -q tests/acceptance/overland_route_planner_mvp/test_slice_12c.py
  -> 138 skipped (pending: slice_12c not enabled yet)

uv run pytest -q --run-pending=slice-12c tests/acceptance/overland_route_planner_mvp/test_slice_12c.py --tb=line
  -> 138 failed, 0 errors, 0 passed (90 scenarios; 14 outlines expand to 62 rows); exception class of every failure: AssertionError (138)
```

D315 applied (keys are index ids, addresses from the index, `rebuilds_not_set_up`); re-run after it. Class of every case: `MISSING_FUNCTIONALITY` (an `AssertionError` in a Then, or in the last Given that needs the built thing: the routes answer 404, the setting is absent, the scripts do not exist). No case is `IMPORT_ERROR`, `FIXTURE_BROKEN`, `SETUP_FAILURE`, `WRONG_ASSERTION` or `OBSERVABLE_NOT_AT_PORT`. The 33 `@ui` scenarios are `test.fixme` (not run).

Fixture-theater checks (a scenario that passes before the feature exists is a defect): two cases passed in the first revised run and were tightened: "Installing again ..." now starts from the helper installed by an older release (a different line must be replaced), and "The refresh says nothing about its steps when not asked" now requires the refresh to have run on the list. Also kept from the first pass: the "not started before its time", "cancelled just before", "deploy running tried again" and "outline cannot be fetched" scenarios require the helper to have run (its `helper-seen` file) and the refresh to name the region itself.

| Scenario (test function) | Cases | Class | What fails now |
|---|---|---|---|
| the planner names the regions and the date of the served map | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| before the first rebuild from the app the planner gives the map date and no regi | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a region is found in the catalogue by name with its parent and what the map alre | 2 | MISSING_FUNCTIONALITY | the catalogue did not answer: 404 |
| two regions with the same name are told apart by their parent | 1 | MISSING_FUNCTIONALITY | the catalogue did not answer: 404 |
| a search for a region needs at least two letters | 1 | MISSING_FUNCTIONALITY | the search answered 404 |
| a change is summarised before it is written and each chosen region s border is f | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| planning a change leaves the served map as it is | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a change that cannot be applied is refused with the reason and nothing is writte | 3 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a region far from the others is information not a refusal | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| changing the road map is not offered when the changes cannot be stored | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a change is refused when the changes cannot be stored | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| the catalogue is fetched with the planner s name and only region details are ask | 1 | MISSING_FUNCTIONALITY | the list was asked for 0 times |
| the catalogue is kept so a restarted planner does not ask for it again | 1 | MISSING_FUNCTIONALITY | the list was asked for 0 times |
| the catalogue is fetched again after a week | 1 | MISSING_FUNCTIONALITY | the list was asked for 0 times |
| the kept catalogue is used when the region service does not answer | 1 | MISSING_FUNCTIONALITY | precondition: the first search did not work |
| the size of a region is asked once and remembered | 1 | MISSING_FUNCTIONALITY | the size of Utah was asked 0 times |
| the served map is the one whose map data carries the date the routing engine rep | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| after a rollback the older map is the one served | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a map whose regions cannot be read is unknown never an error | 4 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a damaged region border is reported as a reason and the map stays unknown | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| while the routing engine is stopped for the build the last known map is still na | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a pending change is kept for the helper and no list of regions is written by the | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a cancelled change can no longer be taken by the helper | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a place is inside or outside the map by the borders of the regions not by boxes | 6 | MISSING_FUNCTIONALITY | the trip's coverage did not open: 404 {"code":"not_found","message":"Not Found"} |
| a trail is outside when its entry or its exit is outside the middle does not mat | 3 | MISSING_FUNCTIONALITY | the trip's coverage did not open: 404 {"code":"not_found","message":"Not Found"} |
| without the regions of the map the planner says the coverage is unknown and warn | 1 | MISSING_FUNCTIONALITY | the trip's coverage did not open: 404 {"code":"not_found","message":"Not Found"} |
| a pending change does not alter what the trip is judged against | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| stops in areas not linked by land are grouped and the groups are named | 1 | MISSING_FUNCTIONALITY | the trip's coverage did not open: 404 {"code":"not_found","message":"Not Found"} |
| italy southern france and spain are linked by land | 1 | MISSING_FUNCTIONALITY | the trip's coverage did not open: 404 {"code":"not_found","message":"Not Found"} |
| without southern france spain is on its own | 1 | MISSING_FUNCTIONALITY | the trip's coverage did not open: 404 {"code":"not_found","message":"Not Found"} |
| the map settings no longer name a road map area and say whether place search is  | 1 | MISSING_FUNCTIONALITY | {'tile_url': '`https://tile.opentopomap.org/{z}/{x}/{y}.png'`, 'attribution': 'Map data: © OpenSt |
| a place name is answered with up to five places each with its region | 1 | MISSING_FUNCTIONALITY | the search answered 404 |
| no contact detail is ever sent to the search service | 1 | MISSING_FUNCTIONALITY | expected one of the requests the search service saw, found 0 |
| nothing is sent to the search service unless a search is asked for | 1 | MISSING_FUNCTIONALITY | {'tile_url': '`https://tile.opentopomap.org/{z}/{x}/{y}.png'`, 'attribution': 'Map data: © OpenSt |
| only the typed words reach the search service | 1 | MISSING_FUNCTIONALITY | expected one of the requests the search service saw, found 0 |
| two different searches in a row are a second apart | 1 | MISSING_FUNCTIONALITY | expected two of the requests the search service saw, found 0 |
| the same search again is answered from memory and sends nothing | 1 | MISSING_FUNCTIONALITY | ('{"code":"not_found","message":"Not Found"}', '{"code":"not_found","message":"Not Found"}') |
| pressing search twice at once sends one search | 1 | MISSING_FUNCTIONALITY | ('{"code":"not_found","message":"Not Found"}', '{"code":"not_found","message":"Not Found"}') |
| a name that matches nothing is an empty answer not an error | 1 | MISSING_FUNCTIONALITY | the search answered 404 |
| a search service that is busy down or garbled leaves the trip unchanged | 4 | MISSING_FUNCTIONALITY | the search answered 404 |
| after a busy answer the search service is left alone for a minute | 1 | MISSING_FUNCTIONALITY | the search answered 404 |
| a name shorter than two letters is refused before anything is sent | 1 | MISSING_FUNCTIONALITY | the search answered 404 |
| switching place search off removes it from the add menu | 1 | MISSING_FUNCTIONALITY | {'tile_url': '`https://tile.opentopomap.org/{z}/{x}/{y}.png'`, 'attribution': 'Map data: © OpenSt |
| a search is answered as not available when place search is switched off | 1 | MISSING_FUNCTIONALITY | the search answered 404 |
| leaving the search address empty means the usual address not off | 1 | MISSING_FUNCTIONALITY | {'tile_url': '`https://tile.opentopomap.org/{z}/{x}/{y}.png'`, 'attribution': 'Map data: © OpenSt |
| a result outside the road map joins the trip as a kept warned place | 1 | MISSING_FUNCTIONALITY | {"code":"not_found","message":"Not Found"} |
| the planner shows the step the helper has reached | 4 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| planning is paused from the build until the switch ends and the planner says whe | 3 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a rebuild that stopped for lack of space says so with the numbers and the served | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| every way a rebuild can fail is told in plain words not as a code | 14 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a rebuild that ended well shows the new regions and date once the new map is ser | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| refresh map data asks for the same regions and shows the same cost | 1 | MISSING_FUNCTIONALITY | no summary: 404 |
| only one change is pending at a time | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a planned change cannot be cancelled once the helper has taken it | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a rebuild is refused on a day that already has a map with the next day and time  | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a new map left behind by a failed switch uses the day up | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a rebuild that failed before the switch leaves no map so the day is not used up | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a start time must be between two minutes and fourteen days ahead | 4 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| without the helper the planner says rebuilds are not set up and refuses the chan | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| a waiting change that the helper has not looked at for minutes says rebuilds are | 1 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 {"code":"not_found","message":"Not Found"} |
| the helper is installed once as one timed job of the deploy user | 1 | MISSING_FUNCTIONALITY | assert_state_delta: 1 violation(s) detected: kind='predicate_failed' key='schedule.helper_lines |
| the install folder may have spaces in its name | 1 | MISSING_FUNCTIONALITY | assert_state_delta: 1 violation(s) detected: kind='predicate_failed' key='schedule.helper_lines |
| installing again replaces the helper s own timed job and keeps the other jobs as | 1 | MISSING_FUNCTIONALITY | assert_state_delta: 1 violation(s) detected: [+1 more line; full report in element text] |
| the helper is added beside the other timed jobs which are kept exactly | 1 | MISSING_FUNCTIONALITY | assert_state_delta: 1 violation(s) detected: kind='predicate_failed' key='schedule.helper_lines |
| uninstalling removes only the helper s timed job | 1 | MISSING_FUNCTIONALITY | assert_state_delta: 1 violation(s) detected: [+1 more line; full report in element text] |
| a pi whose timed jobs cannot be read is left alone | 1 | MISSING_FUNCTIONALITY | exit 127: bash: scripts/road-map-helper.sh: no such file or directory |
| the helper says whether it is installed | 2 | MISSING_FUNCTIONALITY | exit 127: bash: scripts/road-map-helper.sh: no such file or directory |
| a pi that cannot take the helper does not fail the deploy | 1 | MISSING_FUNCTIONALITY | expected one warning about the helper, found [] |
| removing the app from the pi removes the helper s timed job first | 1 | MISSING_FUNCTIONALITY | assert_state_delta: 1 violation(s) detected: [+1 more line; full report in element text] |
| a request is taken at its time and the refresh runs on the regions it names | 1 | MISSING_FUNCTIONALITY | the refresh downloaded 0 times: bash: scripts/road-map-runner.sh: No such file or directory |
| a request is not started before its time | 1 | MISSING_FUNCTIONALITY | the helper did not run |
| a request that is not exactly what the planner writes is refused and nothing run | 8 | MISSING_FUNCTIONALITY | the helper did not run |
| the helper s containers run as an ordinary user without network and without the  | 1 | MISSING_FUNCTIONALITY | the helper started no container for the changes: bash: scripts/road-map-runner.sh: No such file |
| a request cancelled just before the helper looks is not started | 1 | MISSING_FUNCTIONALITY | the helper did not run |
| a refresh refused because a deploy is running is tried again the next minute | 1 | MISSING_FUNCTIONALITY | the helper did not run |
| two helpers at the same minute the second leaves at once | 1 | MISSING_FUNCTIONALITY | exit 127: bash: scripts/road-map-runner.sh: No such file or directory |
| a rebuild the pi lost before the switch is recorded as interrupted and the old m | 1 | MISSING_FUNCTIONALITY | result: ''; bash: scripts/road-map-runner.sh: No such file or directory |
| a rebuild the pi lost after the switch is recorded as done | 1 | MISSING_FUNCTIONALITY | result: ''; bash: scripts/road-map-runner.sh: No such file or directory |
| a rebuild the pi lost is not touched while a deploy is running | 1 | MISSING_FUNCTIONALITY | the helper did not run |
| the refresh refuses for lack of disk with the numbers and the helper keeps them | 1 | MISSING_FUNCTIONALITY | result: ''; bash: scripts/road-map-runner.sh: No such file or directory |
| a refresh from a list of regions downloads those regions each to its own numbere | 1 | MISSING_FUNCTIONALITY | compose -p overland --env-file .env --env-file routing.env --profile routing --env-file release |
| a region whose border file cannot be fetched stops the refresh before anything i | 1 | MISSING_FUNCTIONALITY | tiles-refresh: tileset 20270201; downloading and merging while the old tileset serves curl: (22 |
| the refresh reports its steps in order | 1 | MISSING_FUNCTIONALITY | [] |
| the refresh says nothing about its steps when not asked | 1 | MISSING_FUNCTIONALITY | the refresh did not run on the list |
| the refresh builds the list of the map s regions itself and it travels with the  | 1 | MISSING_FUNCTIONALITY | the new map has no list of regions: ['SHA256SUMS', 'admins.sqlite', 'default_speeds.json', 'tim |
| the checked files list covers the regions list and the borders too | 1 | MISSING_FUNCTIONALITY | ['admins.sqlite', 'default_speeds.json', 'timezones.sqlite', 'valhalla.json', 'valhalla_tiles.t |
| seeding a map again still recognises the same five files after the list grew | 1 | MISSING_FUNCTIONALITY | exit 1: tiles-seed: checksums of the source files (this takes a while) tiles-seed: tilesets/202 |
| the disk the refresh needs grows with the download | 3 | MISSING_FUNCTIONALITY | esh: stopping the routing engine; a plan being calculated now ends with 'Routing engine unreach |
| a refresh refused because a deploy is running says so and writes no failure | 1 | MISSING_FUNCTIONALITY | 1 |
| the helper counts as set up while it looked less than five minutes ago | 2 | MISSING_FUNCTIONALITY | the planner has no road map to show: 404 |
