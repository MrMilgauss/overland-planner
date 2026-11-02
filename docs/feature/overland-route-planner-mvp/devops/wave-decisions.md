# DEVOPS Decisions -- overland-route-planner-mvp

Wave: DEVOPS (platform design) | 2026-11-02 | nw-platform-architect (Apex). Full tables: `feature-delta.md` "## Wave: DEVOPS". Environments: `environments.yaml`. KPI instruments: `docs/product/kpi-contracts.yaml`. Requests to DESIGN: `upstream-changes.md`.

## Key Decisions
- **D80** Environments: dev-mac (no Docker, mock), ci-github-amd64, ci-github-arm64, pi-prod; ephemeral pi-perf; optional pc-amd64.
- **D81** One compose project `overland` in `~/apps/overland-planner/`: `planner` (`init: true`, solver child inside), `valhalla` (from slice 06a), `valhalla-build` (profile), `planner-perf` (profile `perf`), `valhalla-tunnel` (profile `ops`). Networks `edge`, `routing` (internal), `egress`. Explicitly named volumes `overland_planner-data`, `overland_valhalla-data`, `overland_perf-data`.
- **D82** Planner on `${PLANNER_BIND:?}` = `192.168.1.10:8080` on the Pi (verified free; `.env.example` 127.0.0.1, D174). Valhalla never published. Ops ports 127.0.0.1:18080/18002 only while a target runs.
- **D83** Caps: planner 1g / 1 CPU; Valhalla 4g / 2 CPUs (D167, OD-9); build 9g (at the measured cap, max 10g) only with serving stopped and after a MemAvailable preflight. `oom_score_adj 500`; per-service log rotation; no `daemon.json`.
- **D84** Multi-stage image on the pinned `python:3.12-slim-bookworm@sha256:e697...d337`, `ortools==9.15.6755`, non-root. amd64 native on `ubuntu-24.04`; **arm64 by default via QEMU + buildx on `ubuntu-24.04`** (personal free plan; only the wheel install and the smoke run emulated, nothing is compiled; arm64 job about 2x native). Native `ubuntu-24.04-arm` is opt-in via the repo variable `ARM64_RUNNER`. One GHCR manifest list `ghcr.io/mrmilgauss/overland-planner` (owner name required before slice 01a CI); SBOM + provenance; deploy by digest only.
- **D85** Locking: `uv.lock`, `package-lock.json`, every image by digest, actions by SHA, grouped weekly Dependabot. Bumping the solver, base image or Valhalla triggers re-calibration and fixture re-recording.
- **D86** CI: `ci.yml` (lint, test-python, golden-order, test-web, image-amd64, image-arm64 + smoke, e2e, mutation, publish) and `weekly.yml` (re-scan, audits, deep properties, extra browsers).
- **D87** Local gates via pre-commit: pre-commit < 30 s, pre-push < 5 min, mirroring the CI commit stage.
- **D88** Trunk-based on `main`. No branch protection assumed (personal free plan, private repo). Deployable = CI-green main SHA, enforced only by the deploy preflight.
- **D89** Recreate, manual pull-based `make deploy` -> attestation verify -> `scripts/deploy.sh <digest>`: lock, preflight, pull, stop, snapshot, `up -d --wait` on 127.0.0.1, smoke, publish on `PLANNER_BIND`, record, auto-rollback (D165, D171).
- **D90** Rollback contract: previous digest. Every migration has a CI-tested `downgrade()`, and the app refuses an unknown (newer) DB revision. Order: switch -> downgrade with the current image -> restore the predeploy snapshot.
- **D91** No backups (user, 2026-11-02). Only rollback safety on the Pi: the ADR-018 pre-migration copy and the D89 predeploy snapshot (current + previous deploy). `make backup`, Mac copies, weekly backups, `make restore` and the restore drill were removed. **Accepted risk:** Pi/NVMe/volume loss = all project data lost; RPO for device loss undefined; RPO = 0 only for a deploy or migration that fails before the LAN publish (D165). After the publish, writes are kept by a digest-only rollback, but a schema downgrade can lose data only the newer schema holds.
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
- **D102** (revised by D179; slices per PO split D145) **00a** ci-and-image = CI jobs, publish gating, permissions, caches/budgets, scans, weekly.yml, Dockerfile. **00b** planner-on-the-pi = planner-only compose, hardening, bind check, loopback deploy/rollback, pointers, attestation verify, `make diag` (docker stats). **01a** = items on the Pi (mock), consumes 00a/00b. **03-ops** perf-tooling = job log, timings, `/api/diagnostics`, golden order (CI + Pi), perf-pi (mock), CPU-cap re-verify, perf network test. **03** = solver perf. 05 = K4 fields. **06a-ops** valhalla-service = Valhalla service, `routing.env`, tileset seeding + sha256-checked spike cleanup, tunnel network test, contract-live, acceptance-pi, e2e perf. **06a** = adapter. 11 = K1/K6.

## Final review gate decisions (D160-D179, 2026-11-02)
Source: `distill/review-gate-fixlist.md` (Forge F-01..F-31; UD-1, UD-3, OD-1, OD-9). Full text in feature-delta D160-D179.
- **D160** publish: `always() && !cancelled()` + explicit `needs.*.result` checks; optional jobs (golden-order, mutation) join `needs` and the expression only in the slice creating them.
- **D161** `packages/id-token/attestations: write` at job level on jobs 5, 6, 9; push steps gated to main.
- **D162** Job 2 runs `npm ci && vite build` itself (UD-1); WS checks the real page; no fallback shell. Closes UI-2.
- **D163** amd64 image reaches e2e as a 1-day artifact (`docker save`/`load`); branches never write to GHCR.
- **D164** `planner-perf`, `valhalla-tunnel` on `edge` + `routing` (internal-only networks publish no ports); config + reachability test before use.
- **D165** Deploy smoke on 127.0.0.1, then publish (publish = write gate); post-publish failure = digest-only rollback.
- **D166** `VALHALLA_TILESET` in `routing.env` (tiles-* only); deploy preserves unknown keys; app rollback never changes the tileset.
- **D167** CPU caps planner 1, valhalla 2 (server_threads 2), build 3 with serving stopped; re-verify at perf-pi.
- **D168** `/data` probe per ADR-011 (UI-1): real in jobs 6/7 on named volumes, FakeMountTable in job 2; WS `DATA_DIR` under the workspace; `df -T`.
- **D169** Caches (uv, npm, buildx gha); branches run jobs 1-4 (no browser check on branches); <= 1,500 runner-min/month (~45 per main push); 500 MB storage: image ~130 MB/arch (estimate, measured at 00a), GHCR keeps only the latest release, Pi keeps its last 3 locally, e2e artifact deleted after use, weekly storage report.
- **D170** pip-audit + npm audit blocking; Trivy vuln,secret on both arches; `.dockerignore`; job 7 `-m "compose or security"`; DEVOPS-owned `PENDING_FLAGS` in jobs 2 and 7 (today slice-00b, slice-01a), extended as slices go GREEN; weekly ZAP baseline non-blocking.
- **D171** `gh attestation verify` in `make deploy`, fail closed.
- **D172** Availability SLO dropped (not measurable on one Pi).
- **D173** Planner: cap_drop ALL, no-new-privileges, read_only + /tmp tmpfs.
- **D174** `${PLANNER_BIND:?}`; `.env.example` 127.0.0.1.
- **D175** Golden order also on the Pi at every perf-pi.
- **D176** Default deploy SHA = newest green main SHA with release.json; pointers prev + prev2; `commit_ts` in releases.log; DORA in kpi-contracts `delivery_metrics`.
- **D177** K5 claim gate = cold exactly-60-item plans at perf-pi (authoritative; retried / P2>700 included and counted). Diagnostics: p95 per size band (<=30, 31-59, 60, 61-70); done, failed and cancelled all counted (elapsed as lower bound), shown separately. ADR-014 to match (DV-12).
- **D178** Low items: smoke on `${PLANNER_BIND}`, DHCP reservation, `make diag` at 00b = docker stats (closes UI-16), `ubuntu-24.04` pin, GHCR token check, `*.gpx` gitignore, spike-cleanup sha256, Basic auth recommended.
- **D179** D102 mapped to the PO slices 00a, 00b, 01a, 03-ops, 03, 06a-ops, 06a (D145).

## Infrastructure Summary
- **Topology**: one Raspberry Pi 5 (16 GB, aarch64, Debian 13, Docker 29.5.3/Compose v5.1.4) shared with household services. One compose stack: planner (FastAPI + Svelte SPA + short-lived OR-Tools child) on the LAN at port 8080; Valhalla 3.9.1 on an internal network; one-shot tile build and ephemeral perf/tunnel helpers under profiles.
- **Delivery**: GitHub Actions (private repo, personal free plan) builds and tests on hosted runners and builds amd64 natively and arm64 under QEMU by default (native arm64 opt-in). It pushes a digest-pinned manifest list to GHCR. Deploy is manual and pull-based from the Mac over ssh. The Pi has no runner and no inbound exposure.
- **Strategy**: Recreate (10-30 s downtime); rollback by previous digest with an explicit schema/data rollback order.
- **Data**: SQLite WAL + versioned files on `overland_planner-data`. **No backups** (user decision): only rollback snapshots on the same NVMe. Valhalla tilesets on `overland_valhalla-data`, rebuildable, previous kept.
- **Observability**: JSON logs with rotation, Docker healthchecks, `/healthz` + `/api/health`, `/api/diagnostics` (from 03-ops). SLO: K5 only (perf-pi authoritative); no availability SLO (D172).
- **Measured basis**: e2e stage sum 63.7 s (73.7 s with UI + reserve) vs 180 s; solve p95 47.6 s; Valhalla steady 1.3 GB, peak 1.6 GB of 4g; build 34 min at 9 GiB; MemAvailable 12.3 GB; disk free 221 GB.

## Constraints Established
- Images are referenced by digest only. Only CI-green main SHAs with a verified attestation are deployable (D171).
- No command touches resources outside compose project `overland`. No `prune`, no `daemon.json`, no edits to other stacks or to pihole/caddy.
- Valhalla is never published. Ops access is ephemeral and loopback-bound. The planner is reachable from the LAN only after its loopback smoke passed (D165). `PLANNER_BIND` must be set (D174).
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
