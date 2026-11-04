# ATDD Infrastructure Policy

Per `nw-distill` § Project Infrastructure Policy. One file per project. Apply-if-exists; write-if-absent; rewrite with `--policy=fresh`. Git history is the audit trail.

Bootstrapped by DISTILL of `overland-route-planner-mvp` (2026-11-02) with the user's decisions of 2026-11-02; revised in the final-gate fix round (D180-D192). Decision references: `docs/feature/overland-route-planner-mvp/feature-delta.md` (## Wave: DISTILL).

## Driving
| Port | Mechanism | Note |
|---|---|---|
| HTTP API (`/api`, `/healthz`) — default | In-process: the real FastAPI app built by the production composition root `overland_planner.bootstrap.app_factory.create_app(environ, external=...)`, driven with Starlette `TestClient` | Most scenarios. `environ` uses the documented `.env` keys (brief §12). Responses follow brief §5 "HTTP contract" (error envelope `{code, message}`, D130) |
| HTTP API — walking skeleton and `@wiring_e2e` | Real `uvicorn --factory overland_planner.bootstrap.app_factory:create_app` process (cwd = repository root) on a free loopback port, real HTTP with httpx, stdout/stderr read to the end | WS + start-up scenarios: exit code, one `app.started` line, one `health.startup.refused` line |
| Browser UI (Svelte SPA) | Playwright (`tests/e2e/`, TypeScript) against `make run-local` (uvicorn + built SPA) | Only `@ui` journeys. The WS checks the real built page: CI job 2 builds the web app itself (UD-1, D162); no placeholder shell |
| Deployment description (`deploy/compose.yaml`) | Read statically with PyYAML (no Docker) | 00b "stays on the home network" |
| Deployment commands (`make deploy`, compose up on the Pi / PC, image build) | Run for real on the named host, only with `--run-external` (ssh to pi-host, Docker on an amd64 PC, CI job 7 `-m "compose or security"`) | 00b `@requires_external` scenarios (review L-06). Pi runs need a start time named by the user |
| CLI | n/a (Phase 2) | |

## Driven internal (real)
| Port | Mechanism | Note |
|---|---|---|
| Repositories + UnitOfWork (SQLAlchemy 2 + Alembic on SQLite) | Real SQLite in a per-test data folder under the workspace: `$PLANNER_TEST_WORKSPACE` or `<repo>/.data/acceptance/<id>/data` (CI: under `$GITHUB_WORKSPACE`), never the OS temp folder (ADR-011 D121, review H-02) | A "restart" = dispose the app and build a new one on the same `DATA_DIR`. Folder removed after the test |
| `FileStore` (versioned track files, originals) | Real `LocalFileStore` in the same data folder | |
| Leg cache / point cache | Real (same SQLite) | Counted through the real `CountingRoutingProvider` wrapper |
| `TourSolver` (OR-Tools child process) | Real `OrToolsTourSolver` child, small deterministic `SOLVER_BUDGET` for speed | Waivers W1/W2 below |
| `TrackFileParser` / `GpxWriter` (gpxpy + defusedxml) | Real | GPX output validated with xmlschema against the vendored GPX 1.1 XSD (`tests/acceptance/overland_route_planner_mvp/fixtures/schemas/gpx-1.1.xsd`) |
| `EventLog` (structlog JSON to stdout) | Real; read from the uvicorn process stdout (or `capfd` in-process) | |

## Driven external / non-deterministic (fake)
| Port | Fake | Note |
|---|---|---|
| `RoutingProvider` (acceptance) | `MockRoutingProvider` via `ROUTING_PROVIDER=mock` + `MOCK_PLAN=<fixture>`: haversine x 1.3, scripted per-pair levels, per-point snap classes, unreachable points, fault plan | brief §6; a production adapter selected by configuration, so the composition root is unchanged |
| `RoutingProvider` (contract) | `ValhallaRoutingProvider` against recorded Valhalla 3.9.1 answers (respx), from `spike/fixtures/` copied to `tests/contract/fixtures/valhalla-3.9.1/` | Suite `tests/contract/routing_port/` (D181); live variant `@requires_external @real_provider @pi` via `make contract-live` (D95) |
| `RoutingProvider` (Pi-only) | Live Valhalla on pi-host (`planner-perf`) | `@requires_external @real_provider @pi`; `make acceptance-pi` / `make perf-pi` only, never in GitHub CI (D96, D100). "Valhalla" is user vocabulary (results header), accepted in Gherkin (review L-05) |
| `Clock` | `FakeClock` (`tests/common/fakes.py`): fixed UTC time, manual advance | Passed as `ExternalPorts(clock=...)` |
| `MountTable` (host mount table for the `DATA_DIR` persistence probe, D121) | `FakeMountTable(entries)` in-process: default `[("/", "ext4")]`; `FakeMountTable.with_mount(DATA_DIR, "overlay")` for "would not survive a restart" | Passed as `ExternalPorts(mount_table=...)`. Server-process scenarios use the real `ProcMountTable` (macOS: `not_applicable`; Linux workspace: real fstype); there is no fake channel into the process (D182). Real container case: `@requires_external @compose` (CI job 7) |
| Map tiles | Not exercised (static URL from `GET /api/config/map`) | |
| Geocoder (Nominatim) | n/a (Phase 2) | |

## Waivers (driven-internal port substituted; recorded per nw-distill)
| ID | Port | Substitute | Scope | Why |
|---|---|---|---|---|
| W1 | `TourSolver` | `ScriptedTourSolver` (scripted incumbents, delays, no valid route, abnormal exit, an invalid order) via `ExternalPorts(tour_solver=...)` | Stop / optimisation-limit / feasibility-limit / optimizer-crash / waiting-for-optimizer scenarios (slice 03), the "plan that would break a hard rule" guard scenario (slice 02), and the two slice 01b scenarios where a plan is "still being worked out" (`HoldingTourSolver` in `tests/common/solver_fakes.py`: holds the solve, then hands it to the real solver) | Solver wall-clock timing is non-deterministic, and a real solver cannot be made to emit a rule-breaking order. Sanctioned by ADR-015 "Gold tests" and brief §6 |
| W2 | `TourSolver` probe | A solver that fails its start-up probe (`UnavailableTourSolver` in `tests/common/solver_fakes.py`), via `ExternalPorts(tour_solver=...)` | Only "plans are refused while the optimizer cannot start" (slice 01b) | The aarch64 wheel failure cannot be reproduced on the Mac |
| W3 | Database revision | A data folder created by the real planner, then marked "newer" by an Alembic no-op stub revision on top of the planner's own head (Alembic `stamp`); going back to the newer version = stamping back | Only "an older planner refuses data saved by a newer version" (slice 01a) | A real newer planner build does not exist in the test run. Replaces the hand-written schema and the database-file fingerprint (review H-07, D185) |
