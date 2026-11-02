# ADR-006: Persistence — SQLAlchemy 2 + Alembic on SQLite, content-addressed files on /data

## Status
Accepted (user decision, 2026-11-01). **Partly superseded by ADR-018**, which replaces the in-place `canonical.json` / `display.json` with version-addressed files (review B2) and adds SQLite hardening. Everything else below stands.

## Context
- NFR-3: SQLite for app data, track files on disk. FR-1.2: everything survives restarts on a volume. FR-2.3: originals kept unmodified. HC-1: the canonical direction changes only by the explicit Reverse action. US-17 S4: past runs immutable.
- The schema will change across 12 MVP slices plus Phases 2-3. NFR-6: provider failures never corrupt data.

## Decision
- **SQLAlchemy 2.0** (typed declarative mappers kept in `adapters/persistence`; domain entities are plain classes mapped by repositories) with **Alembic** migrations, applied at startup (`upgrade head`) before probes.
- SQLite in **WAL** mode, `foreign_keys=ON`, `synchronous=NORMAL` (FULL for the plan-run commit), a single Uvicorn worker, at most one plan job per project.
- **Unit of work**: each use case commits once; a plan run (number, snapshot, results) is written in one transaction.
- **File layout** on `/data`:
  - `db/planner.sqlite`;
  - `files/originals/{sha256}.gpx`: byte-identical upload, content-addressed (dedup, identical-file detection FR-8.3);
  - ~~`files/tracks/{track_id}/canonical.json`: full-resolution points in canonical order (rewritten only by Reverse, together with an incremented `direction_version` and a history entry, in one use case)~~ **[superseded by ADR-018: `canonical.v{n}.json`, never rewritten]**;
  - ~~`files/tracks/{track_id}/display.json`: simplified points~~ **[superseded by ADR-018: `display.v{n}.json`]**;
  - `tmp/`.
- **Atomic writes**: write into `/data/tmp`, `fsync`, `rename` into place, `fsync` the directory. Files are written before the DB commit that references them. Orphaned files are swept on startup **[deletion rules superseded by ADR-018 Revision 2: sweep-only deletion with job pins]**.
- **Plan runs** store JSON snapshots (inputs, itinerary, totals, report, warnings) so they never depend on later item edits or deletions.

## Alternatives considered
- **Plain `sqlite3` + `PRAGMA user_version` + numbered SQL files**: smallest footprint, but a hand-made migration runner and hand-written mapping and transaction code.
- **SQLAlchemy with `create_all` and no migrations**: fast to start, but the first schema change breaks existing user data (violates FR-1.2 in practice).
- **Track points in SQLite BLOBs**: possible, but files keep the DB small, make originals directly inspectable, and fit content addressing.

## Consequences
- Positive: versioned schema evolution; transactional plan runs; originals byte-identical (US-11a S3); easy backup (copy `/data`).
- Negative: about 20 MB extra RAM (well within NFR-5); two storage kinds to keep consistent (handled by write ordering + startup sweep).
- Probes: WAL actually enabled, quick_check, round-trip write; file write/fsync/rename round trip; `/data` mount check (ADR-011).

## Amendment (DEVOPS, D90/D94) — 2026-11-02
DV-4 and DV-5, accepted by the user. Additive schema: `items.created_at`, `projects.created_at`, `plan_runs.first_exported_at`, `plan_runs.export_count`, `plan_runs.geometry_completed_at`, `plan_runs.geometry_ms`, plus the `plan_job_log` table (ADR-015 amendment). Every Alembic revision implements `downgrade()`, tested in CI by upgrade -> downgrade -> upgrade on a seeded fixture DB, so a rollback to the previous image digest is possible (DEVOPS D90). Migrations still run at start-up as decided above.
