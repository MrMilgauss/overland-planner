# ADR-011: Composition root — wire, probe, use; degraded mode for a non-persistent volume

## Status
Accepted (user decision on degraded mode, 2026-11-01), **with Amendment 1** (simplified probe enforcement, solver degraded, Valhalla readiness, config validation).

## Context
- Every driven adapter depends on something that can lie: Docker overlayfs without a volume looks writable but is lost on recreate; SQLite WAL can silently not be enabled on some filesystems; an OR-Tools wheel can fail on aarch64; ORS can return HTTP 200 with an error body or null cells; an API key can be invalid.
- US-01b S4: started without a persistent volume, the planner must **start**, show "Data directory is not persistent - projects would be lost on restart" on the home page, and `/healthz` must report unhealthy with the same reason.
- US-01a S1: start-up is one structured log line; `/healthz` returns `{"status":"ok"}`.

## Decision
- The composition root (`bootstrap`) loads config, wires the adapters chosen by config, runs migrations, then calls `probe()` on every adapter **before** serving traffic.
- Outcome per probe class:
  - **Fatal** (DB round trip/WAL/quick_check, file write-fsync-rename round trip, solver known-instance solve, GPX parser/writer round trip, invalid config such as a missing `ORS_API_KEY` for `ROUTING_PROVIDER=ors` **[superseded by Amendment 1: no routing key in the MVP; the solver probe is now degraded, not fatal; fatal config checks are listed there]**): log `health.startup.refused` {component, reason} and exit non-zero (Docker shows the container as restarting or exited).
  - **Degraded, unhealthy**: `/data` is not a mount point or is `overlay`/`tmpfs` (read from `/proc/self/mountinfo`). Log `health.startup.degraded` {reason: `data_dir_not_persistent`}. Serve; `/healthz` returns 503 `{"status":"unhealthy","reason":"Data directory is not persistent - projects would be lost on restart"}`; the home page shows a banner.
  - **Degraded, healthy**: routing provider probe fails (offline at boot). Log `health.startup.degraded` {reason: `routing_provider_unreachable`}. `/healthz` stays `ok`; the provider is re-probed before each plan job and the job is refused with the US-10 S4/S5 message if it still fails.
- `/api/health` returns per-component probe detail (behind Basic auth when enabled).
- **[superseded by Amendment 1: two layers, mypy + gold tests; the AST hook and meta-test are dropped]** Probe contract enforcement in three layers: mypy (every port Protocol extends `Probeable`, typed registry), an AST pre-commit hook (adapter classes must have a non-trivial `probe`), and CI gold tests (a fault catalogue per adapter, including the specific lies above). A meta-test checks that every registered adapter has a catalogue entry.

## Alternatives considered
- **Refuse to start whenever any probe fails**: contradicts US-01b S4 (must start and warn), and would make the app unusable offline for local editing.
- **No startup probes, fail lazily**: data loss on a non-persistent volume would only surface after a restart, the exact failure US-01b exists to prevent.
- **Probe in the Docker healthcheck only**: too late and too coarse; it cannot distinguish fatal from degraded.

## Consequences
- Positive: environment lies are found at boot, with structured evidence; Marco gets an actionable message instead of silent data loss.
- Negative: start-up takes about 1-3 s longer (solver probe in a child process). The probe fault catalogue must be maintained as adapters are added.

## Amendment 1 (Revision 1, 2026-11-01)
- **Location**: the composition root is `overland_planner/bootstrap/app_factory.py::create_app()`, started by Uvicorn in factory mode. Nothing else constructs adapters.
- **Probe enforcement simplified** (review medium finding): two layers.
  - mypy strict: every port Protocol extends `Probeable`; adapters are registered through a typed registry.
  - CI gold tests: a fault catalogue per adapter.
  The AST pre-commit hook and the meta-test are **dropped**. Residual risk: a new adapter without a catalogue entry. Mitigation: a code-review checklist item (accepted by the user, D63).
- **Solver probe failure -> degraded, unhealthy** (no longer fatal). The app serves catalog functions; plan requests are refused with "Optimizer unavailable - nothing was changed"; `/healthz` returns 503 with reason `optimizer_unavailable`.
- **Routing engine (Valhalla)**: a probe failure at boot is expected while tiles load. It is degraded and healthy. The probe is re-run every 60 s and before each job, and jobs are refused until it passes (ADR-013 §8). Probe: `/status` + a 2x2 Torino <-> Susa matrix with `4x4.v1`; the dataset tag is read from `/status`. Probes bypass the leg counter.
- **Config validation (fatal)**:
  - `MAP_TILE_URL` containing key-like query parameters (`key`, `apikey`, `api_key`, `token`, `access_token`) is rejected, because keys would leak to every browser (NFR-4);
  - upload caps must be positive;
  - limits are ordered: `FEASIBILITY_LIMIT_S <= OPTIMISATION_LIMIT_S`.
- **Security warning**: when basic auth is not configured, `security.auth.disabled` is logged at warning level at every start-up.
- **TourSolver probe** (corrected wording): a fixed 6-node asymmetric instance containing one track node and one forbidden arc, solved twice in the child process; expect the known optimum and identical orders.

## Amendment (DEVOPS, D80/D90) — 2026-11-02
- DV-7 (clarification): on non-Linux platforms (macOS dev, which has no `/proc/self/mountinfo`), the `/data` persistence probe returns `not_applicable` and the app stays healthy. Linux behaviour is unchanged.
- DV-5 (accepted by the user): a database revision unknown to the image is a **fatal** probe outcome (`db_newer_than_app`), listed with the other fatal storage probes. See ADR-018 amendment.
