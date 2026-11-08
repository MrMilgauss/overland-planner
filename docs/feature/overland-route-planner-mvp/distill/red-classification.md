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
| 11 | Removing the Start POI clears the Start | FAIL | MISSING_FUNCTIONALITY | Then "the project has no Start and no End": the removal answers 404 |
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

**Markers and timings** (D199 precedent, decided per scenario in `test_slice_02.py`): `solver_child` on every scenario that runs a real solve in the solver child or a browser (#1, #4, #5, #12, #15, #16, #17, #20, plus #13 tagged in the feature); each takes 0.4-1.1 s here (the browser one 3.9 s), but they belong to CI job 2 like 01b's. The three properties #2, #3, #6 have no child (in-process solve) and stay in pre-push: 15 s together with profile dev; CI profile ci: 2 min 30 s for the three. #14 is `@slow` (D216): about 4 min in dev with a stand-in, so about 8 min at ci's 200 cases on the Mac; it needs its own CI job. The refusals and settings scenarios (#7-11, #18-19) never reach a solve and run in pre-push (0.2-0.3 s each).

**Open points for DELIVER / the PO** (not resolved by changing scenario text):
- #5: the `TourSolver` port's order names item ids and a track has one node with no reversed variant (HC-1, D45), so "proposes an order that drives the Assietta from Sestriere to Pian dell'Alpe" cannot be said through the port. W1's double names a node the model never offered (`reversed:<track id>`) in the track's place; the guard refuses it as HC-3 (extra/missing item), not HC-1.
- #11: "the plan is marked Stale" presupposes a plan run, but the scenario's Given computes none. The Then fails with that reason once removal exists, unless the PO adds a Given (e.g. a computed plan run) or says what Stale means without a run.
- #4: Calculate needs a Start and an End; the scenario names neither, so the Given also makes Casa Marco Start and End.
- #7-8: "has no Start/End" is bound as "had both, then removed the place that was the missing one" (US-04 S4's action), so the refusal must name the missing anchor even when the other one is set.
- #10: "tries to set X as Start" keeps the End as it is (none here), so the anchors must accept an unset End.
- The Thens of the RED scenarios have not run against a stand-in yet; each stops at its first missing piece.
