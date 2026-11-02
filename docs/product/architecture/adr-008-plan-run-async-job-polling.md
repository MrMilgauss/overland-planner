# ADR-008: Plan run as an asynchronous job with 500 ms polling

## Status
**Superseded by ADR-015** (revised FR-5.5 limits, Stop action, incumbent streaming). The 202 + 500 ms polling transport carries over into ADR-015.

Previously: Accepted (user decision, 2026-11-01).

## Context
- A plan request can take tens of seconds: matrix fetch plus a solve of up to 30 s. FR-7.5 requires live progress ("computing 42 new legs / 380 cached"). US-06 S4 shows the run time.
- Run-numbering rules (DISCUSS): only requests that reach the optimizer create runs. Requests refused for a missing anchor or an unreachable/over-quota provider create none. An unroutable-leg failure is a numbered failed run.
- Single user, single worker; optional HTTP Basic auth must also protect progress.

## Decision
- `POST /api/projects/{project_id}/plan-runs`:
  - synchronous pre-checks: anchors present; no active job for the project. On failure it returns 422 (`"Set the Start before optimizing"`) or 409, with no job and no run;
  - otherwise it returns **202** `{job_id}`.
- `GET /api/plan-jobs/{job_id}` returns `state` (`queued | computing_legs | solving | done | refused | failed`), `new_legs`, `cached_legs`, `legs_total`, `plan_run_id` (when created), `message` (refusal text, e.g. "Routing provider unreachable - nothing was changed. Try again later."). The SPA polls it every **500 ms**.
- `PlanJobRegistry` is in memory (one Uvicorn worker), with a bounded thread executor for jobs; the solver itself runs in a child process (ADR-012). Finished jobs are kept for 10 minutes.
- A **plan run is created** only when the leg matrix is complete (the request "reaches the optimizer"). It is persisted in one transaction at the end, as success or failed (unroutable, invariant violation).
- If the process restarts mid-job, the job is lost and no run exists; the user presses Recalculate again (legs fetched so far stay cached).

## Alternatives considered
- **Server-Sent Events**: push without polling, but needs extra handling for proxies and reconnects; polling at 500 ms is trivial for one user.
- **Synchronous request (blocking up to about 40 s)**: no progress (fails FR-7.5); risk of browser and proxy timeouts.
- **Persistent job queue (DB table or broker)**: survives restarts, but unnecessary for one user; adds complexity (ADR-001).

## Consequences
- Positive: simple, testable (the job state machine is pure application logic); progress counts come straight from `LegMatrixBuilder` (A-4 evidence); works behind Basic auth.
- Negative: jobs do not survive restarts; polling traffic (2 req/s during a job) is negligible.
