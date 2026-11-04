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
