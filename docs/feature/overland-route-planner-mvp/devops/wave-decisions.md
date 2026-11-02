# DEVOPS Decisions -- overland-route-planner-mvp

Wave: DEVOPS (platform design) | 2026-11-02 | nw-platform-architect (Apex). Full tables: `feature-delta.md` "## Wave: DEVOPS". Environments: `environments.yaml`. KPI instruments: `docs/product/kpi-contracts.yaml`. Requests to DESIGN: `upstream-changes.md`.

## Key Decisions
- **D80** Environments: dev-mac (no Docker, mock), ci-github-amd64, ci-github-arm64, pi-prod; ephemeral pi-perf; optional pc-amd64.
- **D81** One compose project `overland` in `~/apps/overland-planner/`: `planner` (`init: true`, solver child inside), `valhalla` (from slice 06a), `valhalla-build` (profile), `planner-perf` (profile `perf`), `valhalla-tunnel` (profile `ops`). Networks `edge`, `routing` (internal), `egress`. Explicitly named volumes `overland_planner-data`, `overland_valhalla-data`, `overland_perf-data`.
- **D82** Planner on `192.168.1.10:8080` (verified free). Valhalla never published. Ops ports 127.0.0.1:18080/18002 only while a target runs.
- **D83** Caps: planner 1g / 2 CPUs; Valhalla 4g / 3 CPUs; build 9g (at the measured cap, max 10g) only with serving stopped and after a MemAvailable preflight. `oom_score_adj 500`; per-service log rotation; no `daemon.json`.
- **D84** Multi-stage image on the pinned `python:3.12-slim-bookworm@sha256:e697...d337`, `ortools==9.15.6755`, non-root. amd64 native on `ubuntu-latest`; **arm64 by default via QEMU + buildx on `ubuntu-latest`** (personal free plan; only the wheel install and the smoke run emulated, nothing is compiled; arm64 job about 2x native). Native `ubuntu-24.04-arm` is opt-in via the repo variable `ARM64_RUNNER`. One GHCR manifest list `ghcr.io/mrmilgauss/overland-planner` (owner name required before slice 01a CI); SBOM + provenance; deploy by digest only.
- **D85** Locking: `uv.lock`, `package-lock.json`, every image by digest, actions by SHA, grouped weekly Dependabot. Bumping the solver, base image or Valhalla triggers re-calibration and fixture re-recording.
- **D86** CI: `ci.yml` (lint, test-python, golden-order, test-web, image-amd64, image-arm64 + smoke, e2e, mutation, publish) and `weekly.yml` (re-scan, audits, deep properties, extra browsers).
- **D87** Local gates via pre-commit: pre-commit < 30 s, pre-push < 5 min, mirroring the CI commit stage.
- **D88** Trunk-based on `main`. No branch protection assumed (personal free plan, private repo). Deployable = CI-green main SHA, enforced only by the deploy preflight.
- **D89** Recreate, manual pull-based `make deploy` -> `scripts/deploy.sh <digest>`: lock, preflight, pull, stop, snapshot, `up -d --wait`, smoke, record, auto-rollback.
- **D90** Rollback contract: previous digest. Every migration has a CI-tested `downgrade()`, and the app refuses an unknown (newer) DB revision. Order: switch -> downgrade with the current image -> restore the predeploy snapshot.
- **D91** No backups (user, 2026-11-02). Only rollback safety on the Pi: the ADR-018 pre-migration copy and the D89 predeploy snapshot (current + previous deploy). `make backup`, Mac copies, weekly backups, `make restore` and the restore drill were removed. **Accepted risk:** Pi/NVMe/volume loss = all project data lost; RPO for device loss undefined; RPO for a failed deploy or migration = 0.
- **D92** Tilesets in `valhalla-data/tilesets/<date>/`, served via a volume subpath, current + previous kept. Slice 06a seeds `tilesets/20261101/` from `~/valhalla-spike` (user-approved). Once production serves it and `make contract-live` is green, `~/valhalla-spike` (18.3 GB) is deleted at a start time the user names. Quarterly refresh with routing downtime of about 35-40 min.
- **D93** Observability: JSON logs, healthchecks, ADR-011 probes, `/api/diagnostics` + page from `plan_job_log` + `plan_runs`. No new services.
- **D94** One instrument per KPI, thresholds versioned in `kpi-contracts.yaml`.
- **D95** Contract suite replayed from the SPIKE fixtures in CI (blocking); `make contract-live` through an ephemeral socat forwarder + ssh tunnel at defined triggers.
- **D96** `make perf-pi` on planner-perf (N=10: max e2e <= 180 s, solve <= 55 s; N=30 for re-calibration), only at a start time the user names. CI runs only the golden-order determinism check.
- **D97** mutmut 3.x on domain + application, scoped to changed files, kill rate >= 80%, in DELIVER (Mac) and CI on main. Stryker not adopted.
- **D98** No CI secrets. Pi `.env` (600) for the optional Basic-auth password. GHCR read-only classic PAT on the Pi. A future ORS key would live in the Pi `.env` only.
- **D99** Coexistence: `-p overland` everywhere, no prune commands, safe `uninstall`/`purge` (typed confirmation, no backup)/`image-gc`.
- **D100** `@real_provider`/`@pi` acceptance runs through `make acceptance-pi`, never in GitHub CI.
- **D101** `releases.log` + DORA targets (at least one deploy per slice, lead time < 1 h, change failure rate < 15%, restore < 15 min).
- **D102** Rollout by slice: 01a = CI + image + planner-only compose + deploy/rollback; 03 = job log, timings, golden order, perf-pi (mock); 05 = K4 fields; 06a = Valhalla, tileset seeding + spike cleanup, contract-live, acceptance-pi, e2e perf; 11 = K1/K6.

## Infrastructure Summary
- **Topology**: one Raspberry Pi 5 (16 GB, aarch64, Debian 13, Docker 29.5.3/Compose v5.1.4) shared with household services. One compose stack: planner (FastAPI + Svelte SPA + short-lived OR-Tools child) on the LAN at port 8080; Valhalla 3.9.1 on an internal network; one-shot tile build and ephemeral perf/tunnel helpers under profiles.
- **Delivery**: GitHub Actions (private repo, personal free plan) builds and tests on hosted runners and builds amd64 natively and arm64 under QEMU by default (native arm64 opt-in). It pushes a digest-pinned manifest list to GHCR. Deploy is manual and pull-based from the Mac over ssh. The Pi has no runner and no inbound exposure.
- **Strategy**: Recreate (10-30 s downtime); rollback by previous digest with an explicit schema/data rollback order.
- **Data**: SQLite WAL + versioned files on `overland_planner-data`. **No backups** (user decision): only rollback snapshots on the same NVMe. Valhalla tilesets on `overland_valhalla-data`, rebuildable, previous kept.
- **Observability**: JSON logs with rotation, Docker healthchecks, `/healthz` + `/api/health`, `/api/diagnostics`.
- **Measured basis**: e2e stage sum 63.7 s (73.7 s with UI + reserve) vs 180 s; solve p95 47.6 s; Valhalla steady 1.3 GB, peak 1.6 GB of 4g; build 34 min at 9 GiB; MemAvailable 12.3 GB; disk free 221 GB.

## Constraints Established
- Images are referenced by digest only. Only CI-green main SHAs are deployable.
- No command touches resources outside compose project `overland`. No `prune`, no `daemon.json`, no edits to other stacks or to pihole/caddy.
- Valhalla is never published. Ops access is ephemeral and loopback-bound.
- Every Alembic migration ships a tested `downgrade()`. The app refuses a DB revision it does not know.
- The tile build runs only with Valhalla serving stopped, under `VALHALLA_BUILD_MEM` (default 9g, max 10g), after disk and memory preflights.
- Heavy Pi operations (perf-pi, acceptance-pi, tiles-refresh) start only at a time the user names.
- KPI thresholds live in `docs/product/kpi-contracts.yaml`. Diagnostics never take the SQLite write lock.
- Mutation kill rate >= 80% on changed domain/application files, per feature.
- No secrets in CI, images or git. The Pi `.env` is mode 600.
- Accepted risk (D91): no copy of project data exists off the Pi's NVMe. Device loss = data loss.

## Upstream Changes
- DV-1 ADR-013: "scheduled live run" becomes a manual `make contract-live` at defined triggers (the Pi is unreachable from GitHub).
- DV-2 ADR-015 / brief §9: new append-only `plan_job_log` table (terminal job record with stage timings).
- DV-3 Driving ports: `GET /api/diagnostics` + `/diagnostics` page.
- DV-4 brief §9: `items.created_at`, `projects.created_at`, `plan_runs.{first_exported_at, export_count, geometry_completed_at, geometry_ms}`.
- DV-5 ADR-018/006: mandatory tested downgrades; fatal `db_newer_than_app`.
- DV-6 brief §12: events `plan.job.finished`, `plan.run.geometry_served`; version fields on `app.started` and every line.
- DV-7 ADR-011: the `/data` mount probe is `not_applicable` on non-Linux (dev-mac).
- DV-8 Informational resource figures (221 GB disk, 12.3 GB available).
DV-1..DV-5 were **accepted by the user on 2026-11-02** and recorded as short "Amendment (DEVOPS, D-number)" notes in ADR-006, ADR-011, ADR-013, ADR-015, ADR-018 and brief §15. No ADR decision was rewritten.
