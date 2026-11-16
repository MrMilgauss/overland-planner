# Overland Route Planner MVP, slice 03b: a dead-end trail is driven, then retraced, never reversed

Date: 2026-11-16. Release `3f51d8f` (`3f51d8fe59c1b57731ec498f80bc53dedaa69c9d`, image `sha256:11397001…`), schema 0008 (no migration), deployed on the Pi at 2026-11-15T21:35:55Z. Tag `slice-03b` on `3f51d8f`; `main` is `0ba2689` (a docs-only commit that fixes commit ids in three ADRs). The feature `overland-route-planner-mvp` continues with later slices; this is a slice archive, and the workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

When no road leaves a trail's exit but one leaves its entry, the plan now drives the trail in full and then retraces it from exit to entry as its own Unconfirmed leg, and goes on from the entry. A track is never entered from its exit. A trail that cannot be reached at any level fails the run before any solve, naming the item. The retrace is an itinerary row with its own km and time (counted as off-road driving), it is written to the GPX, and the invariant guard proves its form and hash.

The order is now: fewest Unconfirmed legs (a retrace counts one), then fewest retraces, then road km only; there is no retrace penalty (decision 18, single-phase weighting). The golden order of slice 03 did not change (D223). Existing projects re-solve once, because the fingerprint changed to fp2.

Story: US-19 (J-02). The feature file has 7 scenarios, all blocking in CI.

## Business context

The learning hypothesis "the exit-side retrace can be added without ever producing a reversed track item" survives: the property test plans 1,000 sparse random projects with missing road legs at track exits and never drives a track exit to entry, and never plans a retrace while a road leaves the exit. Dead-end passes such as the Sommeiller can now be part of a trip.

## Steps completed (roadmap phase 07, 13 steps)

| Step | Commit | Outcome |
|---|---|---|
| 07-01 | `711c1fb` | Golden model and order pinned before anything changes (D223) |
| 07-02 | `fbe7225` | Offline road map reads a level per pair; the port can say "no road" |
| 07-03 | `cd53c20` | Leg table and resolver keep levels and "no road"; the retrace rule has one home |
| 07-04 | `f723cca` | Solver model: retrace arcs and the lexicographic order |
| 07-05 | `d01780c` | An unreachable item fails the run before any solve, naming it |
| 07-06 | `49caabd` | Retrace row, leg confidence and honest totals |
| 07-07 | `ac80684` | The guard proves the retrace form and its hash |
| 07-08 | `49e57f2` | Incumbent counts, job line and `plan_job_log` report real values |
| 07-09 | `6eb346a` | GPX marks every Unconfirmed leg and writes the retrace; the web itinerary shows them |
| 07-10 | `5c751a8` | HC-1 property over levels, with retrace adjacency |
| 07-11 | `6d605d4` | ADR-015 endings (D227), ADR-003 diagnostics path, slice 03b as built |
| 07-12 | `1095999` | Carried-over mutation survivors killed |
| 07-13 | `aa70eec` | Slice 03b blocking in CI |

All 75 steps of the feature's roadmap so far have complete DES traces; `des-verify-integrity` exit 0. The commit ids are those of the public history (see "The public repository" for the rewrite).

## Quality gates

| Gate | Result |
|---|---|
| Refactor L1-L6 | `fd9fa95` (L1-L3 in the job and guard), `9c2195e` (shared retrace trip helpers in tests) |
| Adversarial review | Three guard defects, fixed in `378737a`: (1) check 5 now compares each leg's level and reason with the snapshot's table (ADR-009 Amendment 1); (2) an off-road time shown on a stop must equal the one `plan_run.offroad_of` builds, for track stops and retrace rows; (3) `check_order` names a consecutive pair that no road at any level or retrace joins, before the assembler raises |
| Mutation | Local `make mutate BASE=slice-03`: 96.1 % (2,563 of 2,668) over 20 files, 40 min. After the fix-up `SolverModelBuilder` has 6 survivors and `InvariantGuard` 10, all justified in the test-module headers; `b08bebd` killed the rest |
| Suite | 730 passed, 142 skipped, 0 failed on the Mac (12 min 23 s); 738 passed in the scrubbed clone, after copying in the untracked web build for 4 tests that need it |
| CI | Run 43720937934 on `3f51d8f`: success, 12 of 13 jobs ran, job 8 skipped (no domain or application file changed). Job 2 about 14.1 min (target 15), slow-properties about 10.0 min, slow-a6 about 10.3 min, golden-order 1.5 min, e2e 2.3 min |
| DES integrity | All 75 steps complete |

## Pi gate and demo evidence (2026-11-15, orchestrator-run)

| Check | Result |
|---|---|
| `make perf-pi` N=10, 60 items | pass: all 10 runs done, solve 47.31-52.14 s, slowest 52.14 s (limit 55 s); the golden order of I1 and I2 is unchanged on the Pi; the report is `.data/perf/20261115T213840Z.json` |
| `make perf-pi POINTS=20000 N=5` | guard_persist slowest 4.51 s, against D230's 4.5 s; solve slowest 50.58 s; report `.data/perf/20261115T215118Z.json` |
| guard_persist, one retraced 20,000-point track | 118, 124, 181, 191, 203 ms (slowest 0.20 s) on the Sommeiller demo trip with the track densified to 20,000 points; measured through the demo script, not `make perf-pi` |
| Sommeiller demo | In a separate `__demo` project on `planner-perf` (own data volume): Start, then "Colle del Sommeiller" driven from Rochemolles to the pass (12.4 km, reached by a Confirmed 58 km leg), then "Retrace Colle del Sommeiller" as the next row (12.4 km, Unconfirmed, reason "retraces the trail backwards; check it is drivable in reverse"), then Briançon by a Confirmed 64 km leg from the entry. Totals: road 122.0 km, off-road 24.8 km, overall 146.8 km |
| Household projects | 7 projects, items and plan runs identical before and after deploy, perf runs and demo |
| fp2 re-solve | not run on the household projects: pressing Calculate would add runs to them. The user sees it on the first Calculate (one fresh solve, then the memo again). Unit tests cover the fingerprint |

## The CI-minutes incident and the move to a public repository

CI run 43180928253 on `020f546` ended before any job started with "recent account payments have failed or your spending limit needs to be increased": the private repository's free Actions minutes were gone, and the owner does not pay for GitHub. Job 8 (mutation) runs up to 75 minutes on a domain push (D224) and probably used most of them.

Decision (2026-11-12, user): a new public repository, which gets free minutes. A force-push over the old repository was rejected because old commits live on in GitHub (hidden `refs/pull/*`, run logs, artifacts, the package link).

What was done (2026-11-14 and 2026-11-15):

- A bundle of the whole repository was written outside the repository (`~/Documents/backup-overland-before-scrub.bundle`).
- The Pi's address, host name and login, and the Mac username, were taken out of the tracked tree: the Makefile and the deploy scripts read a git-ignored `deploy/pi.env` (template `deploy/pi.env.example`) and stop with "set PI_HOST (see deploy/pi.env.example)" when it is missing (`137e3e9`). The owner's real `deploy/pi.env` stays untracked. It now uses the Pi's IP address, because the Mac stopped resolving the `.local` name; the Pi's host keys were added to `known_hosts` under the IP after their fingerprints matched the ones trusted under the name.
- The history was rewritten in a fresh clone with `git-filter-repo` (`--replace-text` and `--replace-message`; 271 commits, branches `main` and `feat/slice-03b`, tags `slice-01a`, `slice-01b`, `slice-02`, `slice-03`). A scan of all refs and messages, before and after the push, found zero hits for the host, the Mac username, the real address and the usual secret patterns; the author name and email stay in the git metadata, and `LICENSE` names "Lorenzo" as the copyright holder. The scrubbed tip differs from the original in the replaced strings only; the full suite, lint, markdownlint and the golden checks pass there.
- License MIT (`3f51d8f`), `SECURITY.md`, and a "Data" note in the README (OpenStreetMap-derived Valhalla responses in the spike fixtures; synthetic GPX only).
- The old repository was renamed `MrMilgauss/overland-planner-private-archive` (stays private, the rollback). The new `MrMilgauss/overland-planner` was created private, pushed in two pushes (`378737a`, then `3f51d8f`), then made public with secret scanning and push protection, a read-only Actions token, approval for fork pull-request workflows, wiki, projects and discussions off, Dependabot alerts and security updates, and private vulnerability reporting. Branch protection stays off on `main`.
- The old ghcr package was linked to the archive, so the new CI would have received 403: it was deleted (the Pi keeps its local images; the previous three releases were checked read-only first) and the first CI publish created a new package linked to the new repository. It is public, because it inherits the repository.
- Dependabot opened pull requests on the new repository as soon as it was enabled. They have not been reviewed.

Old to new commit ids (the pre-rewrite ids appear in the earlier evolution documents and in `deliver/execution-log.json`, which is machine data and was not edited): step 07-01 `ff4ff2a` is `711c1fb`, 07-02 `7fe17e9` is `fbe7225`, 07-03 `1573f1c` is `cd53c20`, 07-04 `03f5caf` is `f723cca`, 07-05 `13df16e` is `d01780c`, 07-06 `ae94b24` is `49caabd`, 07-07 `5e7d51f` is `ac80684`, 07-08 `120fe89` is `49e57f2`, 07-09 `ff5d8e9` is `6eb346a`, 07-10 `af5c264` is `5c751a8`, 07-11 `bf84d9c` is `6d605d4`, 07-12 `22f1188` is `1095999`, 07-13 `2556f34` is `aa70eec`, refactor `142277f` is `fd9fa95` and `b7432b5` is `9c2195e`, fix-up `020f546` is `378737a` and `c43dd1d` is `b08bebd`. Commit ids of earlier slices in the older evolution documents are pre-rewrite ids; the tags `slice-01a` to `slice-03` point at the rewritten commits (for example `slice-03` is `3ace122`).

## Lessons learned

- **A host name from mDNS is a single point of failure for deploys.** `make deploy` hung for 12 minutes in its first ssh call when the Mac stopped resolving the `.local` name. The Pi's IP address in `deploy/pi.env` avoids it; the deploy script still has no connect timeout, which would have turned the hang into an error.
- **A scrub needs a place for the facts that were constants.** Moving the Pi's details to a git-ignored file only works because a template and a clear error message exist; the tests now use placeholders, so no real value can leak back through a test.
- **Check what the CI actually does on a first push to an empty repository.** The "changes" job treats an unknown base commit as "run everything", so the first push would have run job 8; only the second, incremental push gets the docs-only and code-only shortcuts.
- **The first CI run after a package move fails once.** The image jobs got 403 until the old package was deleted; a rerun of the failed jobs was enough.

## Open items carried to later slices

- 21 non-registry mutation survivors not judged one by one: `plan_request_job` 3, `plan_run_assembler` 6, `fingerprint` 2, `road_leg` 2, `gpx_document_builder` 3, `gpx_export_service` 1, `track_import_service` 6; plus the old 30-32 survivors of `plan_job_registry` (thread and timing code), deferred since slice 03.
- `MemoSource.number` and `.reproducible` are read by no caller (possible dead code; a separate production commit only if the owner says so).
- The `<trk>` element of the retrace kind in the GPX was not independently opened in the 07-11 review (low risk).
- One unexplained single test failure in one full run on 2026-11-11 (723 passed, 1 failed, not identified, not reproduced in later runs): every full run is read with `-rf`.
- Job 8 (scoped mutation) can run 75 minutes on a domain push and never finishes (D224): the owner decides whether to make it manual or weekly now that the repository is public.
- The Pi's `make perf-pi` has no ssh connect timeout and the deploy scripts neither (see Lessons).
- The 20,000-point guard on a dead-end variant was measured through a demo script, not through `make perf-pi`; a `make perf-pi` mode for it does not exist.
- Local housekeeping: the old unscrubbed local branches `feat/slice-01b`, `feat/slice-02`, `feat/slice-03` and `docs/slice-01a-demo` are still in the working copy; they are deleted after the owner confirms that the backup bundle is stored. The ghcr package is public (private only through the browser). The Dependabot pull requests are unreviewed.
- Earlier carry-overs that stay open: D229 K5 diagnostics key; K2 home-page banner (slice 12); leg cache persisted (slice 05); mock latency threads (F11); D222 GPX Viewer 2 wording (slice 11); D219/D202 FR-2.4 names; D210 NaN/inf elevations (slice 08). The owner does not use OsmAnd; Marco and Giulia are personas. The 15 Spanish dogfood tracks stay in `~/Downloads`, and `assietta.gpx` stays out of git (D198).

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-03b-out-and-back-retrace.md`
- Scenarios: `tests/acceptance/overland_route_planner_mvp/slice-03b-out-and-back-retrace.feature`
- Decisions and demo evidence: `docs/feature/overland-route-planner-mvp/feature-delta.md` (D223 and the slice 03b entries; D233 is the new delivery order)
- ADRs: `docs/product/architecture/adr-009-hc-invariant-guard.md`, `adr-015-plan-job-lifecycle-incumbents-stop.md`, `adr-016-road-leg-confidence-levels-lexicographic-optimisation.md`, `adr-017-out-and-back-retrace.md`
- Perf reports on the Mac: `.data/perf/20261115T213840Z.json`, `20261115T215118Z.json` (not tracked)
