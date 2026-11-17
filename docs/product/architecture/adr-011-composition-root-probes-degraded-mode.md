# ADR-011: Composition root — wire, probe, use; degraded mode for a non-persistent volume

## Status
Accepted (user decision on degraded mode, 2026-11-01), **with Amendment 1** (simplified probe enforcement, solver degraded, Valhalla readiness, config validation), the DEVOPS amendment (DV-5, DV-7) and the **final-gate amendment D121** (`DATA_DIR` persistence by filesystem type, `MountTable` port).

## Context
- Every driven adapter depends on something that can lie: Docker overlayfs without a volume looks writable but is lost on recreate; SQLite WAL can silently not be enabled on some filesystems; an OR-Tools wheel can fail on aarch64; ORS can return HTTP 200 with an error body or null cells; an API key can be invalid.
- US-01b S4: started without a persistent volume, the planner must **start**, show "Data directory is not persistent - projects would be lost on restart" on the home page, and `/healthz` must report unhealthy with the same reason.
- US-01a S1: start-up is one structured log line; `/healthz` returns `{"status":"ok"}`.

## Decision
- The composition root (`bootstrap`) loads config, wires the adapters chosen by config, runs migrations, then calls `probe()` on every adapter **before** serving traffic.
- Outcome per probe class:
  - **Fatal** (DB round trip/WAL/quick_check, file write-fsync-rename round trip, solver known-instance solve, GPX parser/writer round trip, invalid config such as a missing `ORS_API_KEY` for `ROUTING_PROVIDER=ors` **[superseded by Amendment 1: no routing key in the MVP; the solver probe is now degraded, not fatal; fatal config checks are listed there]**): log `health.startup.refused` {component, reason} and exit non-zero (Docker shows the container as restarting or exited).
  - **Degraded, unhealthy**: ~~`/data` is not a mount point or is `overlay`/`tmpfs`~~ **[superseded by Amendment (final gate, D121): classified by the filesystem type that holds `DATA_DIR`; "not a mount point" is no longer a criterion]** (read from `/proc/self/mountinfo`). Log `health.startup.degraded` {reason: `data_dir_not_persistent`}. Serve; `/healthz` returns 503 `{"status":"unhealthy","reason":"Data directory is not persistent - projects would be lost on restart"}`; the home page shows a banner.
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

## Amendment (final gate, D121) — 2026-11-02
Resolves UI-1 and UI-12 (review R-01). The decision above is unchanged except for the persistence rule.
- **Persistence rule for `DATA_DIR`.** Resolve `DATA_DIR` to its real path. Take the mount-table entry whose mount point is the **longest prefix** of that path. Classify by that entry's filesystem type:
  - `overlay`, `tmpfs`, `ramfs` -> **degraded, unhealthy** (`data_dir_not_persistent`, same banner and `/healthz` 503 as before);
  - any other type (ext4, xfs, btrfs, a Docker named or bind volume, ...) -> **ok**;
  - no mount table (non-Linux, e.g. macOS) -> **not_applicable**, healthy (DV-7).
- The root filesystem is never checked on its own; it only matters when it is the longest-prefix match. "Not a mount point" is no longer a criterion, so a bare-metal Linux host (CI job 2, a PC without Docker) with `DATA_DIR` on ext4 is healthy, while a container without a volume (`DATA_DIR` on the container's overlay root) stays degraded (US-01b S4).
- **`MountTable` driven port** (`application/ports/host.py`, D105): `entries() -> [(mount_point, fstype)]` or "unavailable". Adapters: `ProcMountTable` (reads `/proc/self/mountinfo`) and `FakeMountTable` (tests). It is an external, non-deterministic port, substituted through `ExternalPorts` on `create_app` (D106). Its probe: the file can be read and parsed and contains an entry for `/`; on Linux a parse failure is treated as degraded (`data_dir_persistence_unknown`), never as ok.
- **Gold catalogue** (the environment lies): `DATA_DIR` on overlay root; on tmpfs; on ramfs; on ext4 under an overlay root (longest prefix wins -> ok); a bind mount of a tmpfs path; a symlinked `DATA_DIR` resolving onto tmpfs; unparsable mountinfo.
- **Test environments.** Real `ProcMountTable` in the CI jobs that run containers on named volumes; `FakeMountTable` in the in-process acceptance suite. The walking skeleton must not use the OS temp directory as `DATA_DIR` (on many Linux hosts `/tmp` is tmpfs, which would correctly report degraded); it uses a directory under the workspace.

## Amendment (slice 06a, D247) — 2026-11-17
The routing provider's probe result is not frozen at start-up. `HealthService` keeps the latest result of each component with the time it was taken; the plan request use case probes the routing provider before each job and stores the result; `/api/health` probes it again when the stored result is older than 60 s. Every other component keeps its start-up result. There is no background re-probe thread: a planner nobody is asking has nothing to refuse. The offline road map's probe stays fatal at start-up (a wrong answer there is a defect); the Valhalla probe is never fatal (`ok` or degraded-healthy), so the planner starts and serves the catalog while the engine is down, loading or of another version (ADR-013 Amendment 4).
