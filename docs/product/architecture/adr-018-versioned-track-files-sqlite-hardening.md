# ADR-018: Version-addressed track files and SQLite hardening

## Status
Accepted (2026-11-01). Revision 2: job pins + sweep-only deletion (review H-2). Partly supersedes ADR-006 (file layout and SQLite settings). Resolves review B2 and the SQLite part of the high-priority finding.

## Context
- ADR-006 rewrote `canonical.json` in place on Reverse. Exporting a historical or stale run after a Reverse would then emit the reversed points, which is an HC-1 violation in the export (review B2).
- Retrace legs (ADR-017) and the guard must read exactly the points a run was planned with.
- SQLite is written by HTTP requests and by plan jobs. Writes must not fail with `database is locked`, and a migration must not destroy data.

## Decision

### Version-addressed track files
- Layout:
  - `/data/files/tracks/{track_id}/canonical.v{direction_version}.json`
  - `/data/files/tracks/{track_id}/display.v{direction_version}.json`
  - `/data/files/originals/{sha256}.gpx`, unchanged.
- **Reverse** use case:
  1. write `canonical.v{n+1}` and `display.v{n+1}` (temp -> fsync -> rename -> fsync dir);
  2. in one DB transaction: `direction_version = n+1`, new entry/exit, history entry, project revision++;
  3. ~~after the commit, delete version n files only if no plan-run snapshot references (track_id, n)~~ **[Revision 2, review H-2: Reverse never deletes. Old versions are removed only by the orphan sweep below.]**
- A **plan-run snapshot** records per track: `track_id`, `direction_version`, `point_count`, `canonical_sha256` (the itinerary snapshot also holds the retrace hashes, ADR-009 Amendment 2). The guard, map, export and retrace geometry read files **by that version** and verify the sha256.
- **Job pins (Revision 2).** When a plan job takes its snapshot, it registers `(track_id, direction_version)` pins for every Included track in an in-memory `FilePinRegistry` (application/platform). The pins are released when the job ends (done, failed, cancelled, timed out, or process exit). After a restart there are no live jobs, so no pins are needed.
- **Orphan sweep** runs at startup and daily. It deletes a version file only if **all** of these hold:
  - no DB row references it (not the current `direction_version`, and no plan-run snapshot);
  - no live job pin references it;
  - it is older than 1 h. The age guard avoids racing an in-flight write.

  The sweep takes the single write lock while it decides, so a job cannot start between the pin check and the delete.

### SQLite hardening
- `PRAGMA busy_timeout = 5000`, WAL, `foreign_keys = ON`.
- A **single writer**: one process-wide write lock serialises all write transactions (HTTP and jobs). Leg-cache writes from a job are batched per matrix response.
- Readers are not blocked (WAL).
- **Pre-migration copy**: when the DB revision differs from the Alembic head, the startup first copies the DB with the SQLite online backup API to `/data/db/backups/planner-{revision}-{timestamp}.sqlite` (the last 3 are kept), then upgrades. A failed upgrade -> startup refused, with the backup path in the log.

### Backup and restore (README)
- Backup:
  1. `docker compose stop planner`
  2. `docker run --rm -v planner-data:/data -v "$PWD":/b alpine tar czf /b/planner-backup.tgz -C /data .`
  3. `docker compose start planner`
- Restore:
  1. stop the planner;
  2. recreate an empty volume;
  3. `tar xzf` into it;
  4. start. Alembic upgrades an older DB after the pre-migration copy.
- Valhalla tiles are not backed up; they can be rebuilt from the recorded extract list.

## Tests
- **Crash consistency**: inject a failure between the file write and the DB commit. The DB still points to version n, the export of an earlier run is byte-identical to before, and the orphan sweep removes v{n+1} after the age guard.
- **Stale export after Reverse**: run #4, Reverse the Assietta, export run #4. The export contains the Assietta Pian dell'Alpe -> Sestriere with the original point order and count, and the run is labelled stale.
- **Concurrent write**: a job writing legs while an HTTP toggle commits. No `database is locked`; both succeed.
- **Reverse during a live job (Revision 2, H-2)**: start a plan job with the Assietta at v{n}, then commit a Reverse (v{n+1}) between job start and the guard, then force an orphan sweep. Expected: no file pinned by the live job is deleted; the run completes on v{n} (guard hashes match), or fails cleanly with a named reason; the new run is immediately Stale (the revision changed). After the job ends and the age guard passes, v{n} is deleted only if no run snapshot references it.
- **Migration with a pre-existing DB**: the backup file is created before the upgrade.

## Alternatives considered
- **Rewrite in place + store points inside the plan-run snapshot**: doubles storage per run (full-resolution points per run) for no benefit over versioned files.
- **Points in SQLite BLOBs per version**: viable, but loses inspectable files and the existing content-addressed original layout.
- **No write lock, rely on busy_timeout only**: long leg-cache batches could still exceed the timeout under bursts; one lock is simpler for one user.

## Consequences
- Positive: historical runs and exports are immutable in fact, not only in the DB; crash-safe ordering; migrations are reversible by copy.
- Negative: old versions stay on disk while any run references them (small: one file per reversal).

## Amendment (DEVOPS, D90/D91) — 2026-11-02
DV-5, accepted by the user, and the user's backup decision.
- **Downgrades and newer databases (D90):** every migration has a CI-tested `downgrade()`. At start-up, a DB revision the image does not know (DB newer than the app) refuses start-up (`health.startup.refused {component: db, reason: db_newer_than_app}`), so a rolled-back image never touches a newer schema. Rollback order: switch digest (same schema) -> `alembic downgrade` with the newer image -> restore the predeploy snapshot.
- **Backups (D91):** the user does not want backups (2026-11-02). The "Backup and restore (README)" procedure above is **not operated as a routine**. What remains, for rollback only: the pre-migration copy decided above, and a predeploy snapshot of the volume taken by the deploy script while the planner is stopped (current + previous deploy kept). **Accepted risk:** both live on the same NVMe; loss of the Pi, its NVMe or the volume loses all project data (RPO undefined for device loss). The decision above is unchanged.
