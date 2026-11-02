# Final review gate — consolidated fix list (2026-11-02)

Four reviewers ran against the full feature-delta.md: PO (Eclipse) needs_revision 1B/5H; Architect (Atlas) conditionally_approved 0B/3H; Platform (Forge) needs_revision 3B/9H; Acceptance (Sentinel) needs_revision 2B/7H. HC-1..HC-5: no violations. Paths relative to /Users/dev/Documents/TravellingOffroaderProblem. Decisions continue at **D121**.

## User decisions (2026-11-02) — authoritative
- **UD-1 (UI-2, home page in CI):** CI job 2 (test-python) runs the web build itself (`npm ci && vite build`, no `needs`, stays parallel with job 4). The walking skeleton checks the real built page. NO placeholder/fallback shell.
- **UD-2 (DoR story size):** scenarios DISTILL derived from DESIGN/DEVOPS decisions (contract checks, limits/caps, start-up refusals, crash consistency, diagnostics) are tagged `@technical` and do NOT count toward the 3–7 UAT band. Split only stories whose user-facing (non-@technical) scenarios still exceed 7 (expected: US-10a, US-02a — verify). Record a fresh DoR PASS.
- **UD-3 (180 s claim population, KPI-1):** the K5 target (p95 ≤ 180 s) counts EVERY cold 60-item plan, including retried jobs and second-pass P2 > 700. Retried / P2>700 counts are reported separately for visibility, not excluded. Remove the exclusions from ADR-014, kpi-contracts.yaml, D66/D67 wording.
- **UD-4 (optimizer ordering, OBJ-1/R-05/R-06):** order = (1) fewest Unconfirmed legs, (2) fewest retraces, (3) objective (road km of the fastest routes, D75, or time). Record as an explicit clarification of FR-5.8/FR-5.1 in REQUIREMENTS.md and ADR-016 §4. RETRACE_PENALTY is a tie-break term only and is NEVER included in reported km/time/objective (fix ADR-017 §1 contradiction; state which value Itinerary/Totals show = real road + retrace km).

## Orchestrator defaults (state them as decisions; user may override later)
- **OD-1 Slice sizing (SLICE-1):** split infra out of the overloaded slices: 01a → 01a (items on Pi, mock routing) + new 00 "CI, image and deploy" (or 01a-ops); 03 → keep solver perf, move golden-order/perf-pi tooling into 03-ops; 06a → split Valhalla service + tileset seeding (06a-ops) from adapter (06a). PO picks exact names/numbering and re-estimates.
- **OD-2 Item ceiling (R-07/SCOPE-1):** supported for the 180 s claim: up to 60 non-anchor items + Start/End (62 nodes, measured). 61–70 items are allowed (REQUIREMENTS §4 range) but the UI shows "large project — calculation may take longer than 3 minutes"; slice 03 re-calibrates at 70 items before the claim is extended. No refusal.
- **OD-3 Multi-file import with one bad file (UI10-1):** import the valid files, list each refused file by name with its reason; nothing partial from a bad file.
- **OD-4 Start+End-only plan (UI10-1):** valid: a Start→End road route with totals.
- **OD-5 Messages (DISTILL-1, MSG-1):** solver-side limit: "No valid route found within the time limit – plan run #N failed"; look-up-side limit: "No valid route found within the time limit – nothing was changed"; valid GPX with no usable track: "X has no usable track". Other UI-9 messages accepted; caps (25 MB, 100 MB, 50 files) configurable.
- **OD-6 Entry/exit labels (PO-1/UI-4):** direction text uses the GPX track name/desc when present, else "entry"/"exit" markers with coordinates; no reverse geocoding in MVP.
- **OD-7 Golden-order fixtures (SPIKE-1):** slice 03 re-creates the seeded instance generator (seed 20261101, 68 Western Alps places, method in spike/findings.md Setup) and commits I1/I2 + golden hash; recorded as a slice-03 pre-requisite.
- **OD-8 Backups (REQ-1):** record the no-backup decision as an accepted-risk note against NFR-3 and J-06 in REQUIREMENTS.md.
- **OD-9 DEVOPS CPU caps (F-08/CPU-1):** planner cpus 1, valhalla cpus 2 (server_threads 2), build stays 3 with serving stopped; re-verify solve ≤ 55 s at perf-pi.

## Architect (DESIGN) fixes — owner nw-solution-architect
Files: docs/product/architecture/brief.md, adr-*.md, feature-delta DESIGN section, REQUIREMENTS annotations only where UD-4/OD-2 need it (coordinate with PO who owns REQUIREMENTS text).
- R-01/UI-1: amend ADR-011 + brief §7: classify DATA_DIR by longest-prefix /proc/self/mountinfo fstype: overlay/tmpfs/ramfs → degraded; other → ok; non-Linux → not_applicable. Never check the root fs. Remove "not a mount point". WS must not use OS temp dir as DATA_DIR. Add MountTable to brief §6 and DESIGN driven-ports table.
- R-02/UI-7: ADR-015 add rows: child completes with no incumbent → numbered Failed run, reason `no_valid_route_found`, immediately (no wait to limit); child exits abnormally → no incumbent: Failed `optimizer_failed`; with incumbent: finalise labelled "not fully optimised (optimizer_failed)".
- R-03/F-2: ADR-018: snapshot read + pin registration in one critical section under the write lock; add named test.
- R-04: fingerprint adds weighting mode, phase-1/phase-2 limits, retrace penalties; test.
- R-05/R-06: per UD-4.
- R-07: per OD-2 in ADR-014 §1.
- R-08: provider_id = valhalla:<version>:<tileset_last_modified>; refuse plan jobs if /status version ≠ pinned.
- R-09/UI-8: ADR-018: check first (read revision read-only; newer → refuse, no copy), then copy, then upgrade.
- R-10/UI-3/R-21: ratify D107 into brief §5: snake_case; error envelope {code,message} with enumerated codes (422 validation_error|missing_anchor; 409 job_active; 503 routing_engine_not_ready|optimizer_unavailable; 413 upload_too_large; 401 unauthorized); RequestValidationError handler; anchor enum start|end|start_end|null; one field-name table for poll payload and plan_job_log (legs_new/legs_cached); ignore_memo on plan-runs with same codes; OpenAPI snapshot in CI.
- R-11: consolidated brief pass: §4 FilePinRegistry; §5 ignore_memo; §6 MountTable; §12 solver child measured 55–59 MB, event catalogue adds plan.job.finished, plan.run.geometry_served; §14 and ADR-015/017 status lines no longer "pending SPIKE".
- R-13/SPIKE-2: one definition of items/pairs everywhere (spike measured 62 nodes ⊇ 60-item requirement).
- R-14: label permissive locate as estimate; P2=720 bounding case (realistic ~600) — under UD-3 no exclusion at 700 anymore.
- R-15: Valhalla concurrency limit is a process-wide semaphore (2); solver: one slot for the claim or note measuring two children at perf-pi.
- R-16: ADR-009 check 5 exempt for leg after a retrace.
- R-17: note guard re-measure with 40×20k-point tracks at slice 03 or document max points/track.
- R-18: Stop in finalising is idempotent (returns the incumbent being written).
- R-19: ADR-018 backup section → "rollback snapshot only; see D91"; volume name overland_planner-data.
- R-20/UI-15: brief §15 "arm64 via QEMU by default; native when ARM64_RUNNER is set".
- Itemise or close F-11..F-20 in the DESIGN gate record.

## PO (DISCUSS) fixes — owner nw-product-owner
Files: REQUIREMENTS.md (annotations), feature-delta DISCUSS section, discuss/journey-plan-overland-trip.feature, docs/product/jobs.yaml/journeys if needed, slices/*.md.
- DOR-1 per UD-2; SLICE-1 per OD-1; DISTILL-1/MSG-1 per OD-5; UI10-1 per OD-3/OD-4; PO-1 per OD-6; REQ-1 per OD-8; SCOPE-1 per OD-2; KPI-1 per UD-3; OBJ-1 per UD-4 (REQUIREMENTS FR-5.8/FR-5.1 clarification).
- KPI-2: U46 wording "sum of stage p95s (estimate); K5 unverified until perf-pi".
- SSOT-1: mark discuss/journey-plan-overland-trip.feature as superseded by tests/acceptance/overland_route_planner_mvp/*.feature (header note), and back-propagate D116 into feature-delta (US-06a S2 both limits; US-06b S4; line ~160 run-numbering rule: look-up-side limit creates no run).
- DEMO-1: real assietta.gpx is a precondition of the 01a demo DoD.
- PROC-1: add U46 line to Revision 6.1 table.
- STAT-1: "max of 10 runs" wording for US-06a S1a/S1b.
- OPT-2: US-08 S5 "the best order found has no more Unconfirmed legs".
- UI-9 difficulty 1–5 and same-file merge recorded as PO decisions; UI-11 "exactly one app.started line" confirmed.
- L-04 (from Sentinel): one action vocabulary "Calculate"/"Recalculate" — PO confirms, DISTILL applies.

## DEVOPS fixes — owner nw-platform-architect
Files: feature-delta DEVOPS section, devops/*, docs/product/kpi-contracts.yaml, brief §15 (coordinate: architect also touches §15 line for R-20 — DEVOPS owns the rest of §15).
- F-01 publish gating: `if: always() && !cancelled()` with explicit result checks; optional jobs added to needs only from the slice creating them.
- F-02 packages:write (+id-token, attestations) at job level on jobs 5 and 6, push step gated to main.
- F-03 per UD-1; close UI-2.
- F-04 image transfer to job 7 (push ci-only digest to GHCR, or save/load artifact).
- F-05 planner-perf / valhalla-tunnel also on a non-internal network, still loopback-published; verify with compose config test before slice 03.
- F-06 deploy: start new planner on 127.0.0.1, smoke, then publish on PLANNER_BIND (publish = write gate) — or correct the RPO claim; prefer the former.
- F-07 VALHALLA_TILESET out of release.env (separate routing.env written only by tiles-refresh); deploy.sh preserves unknown keys; app rollback never changes tileset.
- F-08 per OD-9.
- F-09 record UI-1 rule (architect's ADR-011 amendment) and which CI jobs use the real probe (6, 7 on named volumes) vs FakeMountTable (job 2); WS DATA_DIR not under OS temp dir; job 2 prints `df -T`.
- F-10 caching (setup-uv cache, npm cache, buildx gha cache per arch); runner-minute budget check.
- F-11 OWASP ZAP baseline (weekly or job 7; non-blocking OK, record).
- F-12 job 7 runs `pytest --run-external -m "compose or security"`; .dockerignore; Trivy `scanners: vuln,secret`.
- F-13 `gh attestation verify` in make deploy, fail closed.
- F-14 Trivy on arm64 image too. F-15 pip-audit / npm audit in ci.yml blocking on high/critical.
- F-16 availability from app.started + releases.log → diagnostics uptime_30d, or drop SLO.
- F-17 cap_drop ALL, no-new-privileges, read_only + tmpfs on planner.
- F-18 `${PLANNER_BIND:?...}` fail-closed on Pi; NET-1: .env.example default 127.0.0.1.
- F-19 golden-order check also on the Pi (perf-pi or deploy smoke).
- F-20..F-31 low: smoke uses ${PLANNER_BIND}; DHCP reservation note; deploy default = latest green SHA with release.json; second rollback pointer; commit timestamp in releases.log + DORA into kpi-contracts; K5 diagnostics = server-side proxy, perf-pi authoritative; brief §15 QEMU wording (R-20); make diag at 01a = docker stats only; pin ubuntu-24.04; credential helper / fine-grained token check; .gitignore *.gpx outside synthetic fixtures; spike-cleanup sha256 compare before delete; recommend Basic auth on by default.
- UD-3 in kpi-contracts.yaml (no exclusions; separate counts).

## DISTILL fixes — owner nw-acceptance-designer (runs LAST, after the others)
Files: tests/**, src/overland_planner scaffolds, docs/architecture/atdd-infrastructure-policy.md, feature-delta DISTILL section, distill/*.
- B-01: move 06a/06b @contract scenarios to tests/contract/routing_port/ (D103).
- B-02: business-language rewording (basic auth, planner image, port 8080, apikey URL, "planner stack" …); extend CM-B grep term list (L-13).
- H-01: WS Thens = user observations; health + log assertions → separate @wiring_e2e scenario; "with his trip collection saved".
- H-02: per UD-1 + architect's UI-1 rule; WS DATA_DIR under a workspace dir, not OS temp; fake/real mount channel for the subprocess.
- H-03: record Check B environment mapping.
- H-04: one When per scenario (split compound Whens).
- H-05: slice-11 export as When.
- H-06: Then asserts outcomes, not engine call shapes / storage; record A-4 exception.
- H-07: no internal-file fingerprint universe / hand-written schema; use migration head + future-revision stub, or record waiver.
- UD-2: tag design-derived scenarios @technical; recount per story; feed PO.
- UD-3, UD-4, OD-2..OD-6 scenario impacts; L-01 retag; L-02 property vs examples; L-04 vocabulary (Calculate/Recalculate); L-05 Valhalla name accepted in policy; L-06 deployment driving adapters in policy; L-07 refusal exit code; L-08 join pump threads; L-10/L-11 wording; L-12 story-source path.
- Re-run `uv run pytest -q tests` → RED-for-right-reason; update red-classification.md.

## Hand-offs to DISTILL from the fix round (2026-11-02)

### From PO (D140–D159)
@technical tags (39; paths under tests/acceptance/overland_route_planner_mvp/, line numbers as of the PO's read — re-locate by title):
- slice-01a: 95 packaged planner started without its data storage; 101 data folder the planner cannot write to stops it at start-up; 108 older planner refuses data saved by a newer version; 175 trail file that tries to read other files; 182 trail file above the upload limit.
- slice-01b: 58 plan still being worked out cannot be exported yet; 64 plans refused while the optimizer cannot start; 72 second Optimize while a plan is being worked out.
- slice-02: 41 a plan that would break a hard rule is never shown; 84 a track cannot be made the Start even when asked directly.
- slice-03: 43 the 60-item plan is the same on every machine; 78 feasibility limit reached while roads are still being looked up; 101 closing the planner during a long optimisation; 108 only one plan is calculated per project at a time; 117 Marco's diagnostics show how planning went.
- slice-04: 28 excluding Start or End is refused even when asked directly.
- slice-05: 36 correction across a rounding step; 86 diagnostics count toggle-only recalculations.
- slice-06a: 62 road legs found before the routing engine failed are kept; 86 Torino to Susa read as a Confirmed leg; 92 missing matrix answer confirmed by a route check; 100 one place the engine cannot snap never removes the other legs; 108 large trip asked in batches; 114 checks stop when the engine is not the recorded version; 120 engine failures reported as failures (Outline); 133 passing server hiccup is retried; 140 offline road map reports the same way; 146 the routing engine on the Pi still answers like its recordings.
- slice-06b: 49 restricted road classified from legal and permissive look-up; 56 permissive retry never snaps onto a footpath; 63 summit far from any road cannot be connected.
- slice-07: 44 more files than the upload limit.
- slice-08: 41 reverse interrupted by a crash; 50 trail reversed while a plan is being calculated; 116 sparse forum tracks not flagged as jumps.
- slice-09: 55 chosen map tiles and attribution; 62 map tile address carrying a private key stops start-up.
- slice-11: 50 first export of a big trip records how long planning took; 94 track data that no longer matches the run refuses the export.
Retags: slice-01a lines 125,131,145,189,196 → @US-02c; slice-05 lines 68,74,80 → @US-09b, other slice-05 → @US-09a; US-01a scenarios slice-01a lines 17,25,31,40,48,54 → @slice-00b (US-01a moved to new slice 00b; consider moving them to a slice-00b feature file).
Wording: slice-01a:163 waypoints-only.gpx → "has no usable track"; slice-03:72 → "... - plan run #N failed"; slice-03:78 → "... - nothing was changed"; slice-04:140 Then → "the best order found has no more Unconfirmed legs than the Confirmed order, so it has none"; slice-03:15 + slice-06a:24 Givens → "60 items plus Start and End" and "the slowest of the 10 runs"; "Optimize" → "Calculate"/"Recalculate" (D156). US-06b S4 = slow optimizer (D116). New US-02a S3 "no usable track". US-09b S3 "Clearing one project's leg cache keeps the other project's legs" (new). 61–70 items: notice "Large project - calculation may take longer than 3 minutes" (D146). Multi-file import: valid files imported, refused files listed (D149). Start+End-only plan = direct route (D150).
New slices: 00a ci-and-image, 00b planner-on-the-pi (US-01a), 03-ops perf-tooling, 06a-ops valhalla-service (slices/*.md).

### From architect (D121–D136)
- Poll/plan_job_log field names: legs_new / legs_cached / points_new.
- Error envelope {code,message}; codes 422 validation_error|missing_anchor; 409 job_active; 503 routing_engine_not_ready|optimizer_unavailable; 413 upload_too_large; 401 unauthorized; 404 not_found. Anchor enum start|end|start_end|null. (brief §5 "HTTP contract")
- New job state waiting_for_optimizer (one solver child at a time; stoppable; stopped/timed-out → no run; counts in K5). Stop idempotent: 200 while finalising / on finished job, 404 unknown job.
- Failed reasons no_valid_route_found (immediately) and optimizer_failed; crash with incumbent → "not fully optimised (optimizer_failed)".
- MountTable rule (UI-1 closed): fstype of longest-prefix mount of DATA_DIR; overlay/tmpfs/ramfs → degraded; else ok; non-Linux not_applicable. WS DATA_DIR under workspace (CI: $GITHUB_WORKSPACE), never OS temp.
- Newer DB: refused, nothing copied or written (check first).
- provider_id valhalla:<version>:<tileset>; VALHALLA_EXPECTED_VERSION mismatch → 503 routing_engine_not_ready.
- Retrace penalty never in reported km; Totals = road + off-road incl. retraces.

### From DEVOPS (D160–D179)
- CI job 2 builds the web UI (vite) itself; WS checks the real page.
- Job 7 runs pytest --run-external -m "compose or security".
- PLANNER_BIND required (fail-closed); planner starts on 127.0.0.1 for smoke, then LAN publish.
