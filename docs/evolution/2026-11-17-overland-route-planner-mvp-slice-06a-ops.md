# Overland Route Planner MVP, slice 06a-ops: the road engine serves on the Pi

Date: 2026-11-17. Release `5c68135` (`5c68135dbb9901e41bb3ad8343a861d4e34e42a8`, image `sha256:4b3e3aa9…`), schema 0008 (no migration), deployed on the Pi at 2026-11-17T01:14Z. Tag `slice-06a-ops` on `5c68135`; `main` is one test-and-docs commit ahead (`98422ce`). The feature `overland-route-planner-mvp` continues: this is a slice archive, first of the three slices of release R2a "real roads on a map" (D233), and the workspace `docs/feature/overland-route-planner-mvp/` stays active.

## Summary

Valhalla 3.9.1 now runs in the owner's compose stack on the Pi with the SPIKE-2R map data (tileset `20261101`, map data of 2026-11-01), capped at 2 cores and 4 GB, on an internal network and never published. The planner does not depend on it: it starts, deploys and rolls back whether or not the engine is up (D234). The planner itself still plans on the offline estimate; slice 06a switches it to the engine.

Tools that now exist: `make tiles-seed`, `make tiles-refresh`, `make tiles-rollback`, `make spike-cleanup`, `make contract-live`, `make acceptance-pi`, `make perf-pi MODE=e2e`. CI job 8 (mutation) runs only on manual dispatch (D238).

Enabler slice (D145): no user story and no scenarios of its own. It is demoed with slice 06a.

## Steps completed (roadmap phase 08, 7 steps)

| Step | Commit | Outcome |
|---|---|---|
| 08-01 | `6e8663a` | The engine in the compose stack: profile `routing`, caps, internal network, no published port; the Pi tooling turns the profile on when `routing.env` exists |
| 08-02 | `b5a2dff` | CI mutation job only on manual dispatch (D238) |
| 08-03 | `52a7c86` | `make tiles-seed` and the guarded `make spike-cleanup` |
| 08-04 | `80984c5` | Tile build services, the config overrides file, `make tiles-rollback` |
| 08-05 | `ae65058` | `make tiles-refresh` (the quarterly map-data refresh) |
| 08-06 | `91efd8f` | 32 recorded engine answers with a manifest, the loopback-only tunnel, `make contract-live` |
| 08-07 | `aa9824e` | `make perf-pi MODE=e2e` and `make acceptance-pi` (first run at the slice 06a gate, D236) |

All 82 steps of the feature's roadmap so far have complete DES traces; `des-verify-integrity` exit 0.

## Quality gates

| Gate | Result |
|---|---|
| Roadmap review | NEEDS_REVISION (1 blocker, 8 high), all applied before any step ran (D239) |
| Refactor | No separate pass: the slice is shell scripts, compose and their tests; the shared helpers were extracted into `deploy/scripts/lib.sh` as the steps went (L1-L3). No domain or application code changed |
| Adversarial review | NEEDS_REVISION; every blocking claim checked by the orchestrator. Three refuted, ten confirmed and fixed test-first in `af7ba3e` (D241): an interrupted refresh left the engine stopped; a failed "tileset exists" probe was read as "absent"; unchecked pointer backups; a refresh could record success without proof; tunnel waits could test a stale listener; the live check did not name the map data; float comparison gaps; the CI mutation step lost its exit code |
| Mutation | Not applicable: `make mutate BASE=slice-03b` reports "no domain/application file changed" |
| Suite | 961 passed, 152 skipped, 0 failed on the Mac (12 min 45 s) before the first push; the three later fixes ran the ops suites (479 passed) and the fast suite (900 passed) |
| CI | Runs on `a055e04`, `22a4767`, `5c68135`: success each time, job 8 skipped by design (D238) |
| DES integrity | All 82 steps complete |

## Pi gate evidence (2026-11-17, orchestrator-run)

| Check | Result |
|---|---|
| Before | Memory available 12,860 MB; planner healthy on the slice 03b release; 19 household and planner containers up |
| `make deploy` | Three deploys (`a055e04`, `22a4767`, `5c68135`), each `ok`; the planner was down about 20 s each time |
| `make tiles-seed` | Third run `ok`: Valhalla 3.9.1 healthy on tileset `20261101`, `tileset_last_modified` 1793560782 (the SPIKE-2R value). The first two runs failed their own checks and restored the pointer (see Lessons); nothing was deleted |
| `make contract-live` | 40 passed: the eight live checks answer exactly as recorded (status, Torino to Susa route, 5x5 matrix, island null row and its 442, the 2,501-pair refusal, 170, 171, the empty locate) on the recorded map data |
| After | Memory available 12,595 MB with the engine serving (gate: at least 6 GiB); engine 213 MB idle, 540 MB after the design probes; 20 containers up; nothing published but the planner |
| Household projects | 7 projects, 37 items, 12 runs: identical before and after |
| Not run (D237) | `make spike-cleanup` (deleting `~/valhalla-spike`, 18.3 GB) and `make tiles-refresh` (about 40 min without routing, new map-data date): each waits for a start time the owner names. `make acceptance-pi` and `make perf-pi MODE=e2e` need slice 06a |

## Lessons learned

- **Offline tests of an ops script prove its logic, not the image it drives.** Three facts only the Pi could show (D242): the engine wants `default_speeds.json` beside the tiles or it tries to download it; the map data's identity is the tile file's modification time, which a plain copy loses; the engine adds advisory `warnings` to some answers. Each was caught by the script's own check and undone by it, which is what the guards are for.
- **Make a tool able to finish what it started.** The first failed seed left four verified files in place. Teaching the seed to complete and repair an unserved tileset avoided deleting anything on the Pi.
- **A reviewer without a shell raises alarms that only a check can settle.** "A real address and password are in the tests" was refuted in one read-only comparison on the Pi; "the exit code is lost in a pipe" was confirmed by reading the workflow. Both took minutes.
- **Three deploys for one gate.** Each fix needed a CI run (about 25 min) before `make deploy` would take it. A dry-run mode of the tiles tools against the real image would have found the first two facts before the first push.

## Open items carried to later slices

- Owner actions: name a start time for `make spike-cleanup` (frees 18.3 GB) and, each quarter, for `make tiles-refresh`. The refresh has never run live; its download does not verify Geofabrik's md5 files and its `apt-get` installs are unpinned (D241).
- Map coverage: Italy, Switzerland, Austria and two French Alpine regions. Projects in Spain cannot be planned on real roads until the extract list grows; the tile build already runs at its 9 GB cap.
- A refresh over a dropped ssh session now restores the old engine, but the build itself does not continue: run it from a stable session.
- `make purge` removes the map data volume too (D239).
- Earlier carry-overs stay open (see the slice 03b archive).

## Links

- Slice brief: `docs/feature/overland-route-planner-mvp/slices/slice-06a-ops-valhalla-service.md`
- Decisions: `docs/feature/overland-route-planner-mvp/feature-delta.md` D234 to D242
- ADR: `docs/product/architecture/adr-013-routing-valhalla-self-hosted-mvp.md` Amendment 3
- Logs on the Mac (not tracked): `.data/ops/releases.log`, `.data/ops/tiles.log`
