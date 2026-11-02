# ADR-015: Plan job lifecycle — limits, Stop, incumbent streaming, solver child process

## Status
Accepted; parameters pending SPIKE-1R (2026-11-01). The Stop semantics were confirmed by the user (D60). Supersedes ADR-008 and ADR-012. Resolves review B3.

## Context
- A plan job now runs from seconds up to 30 min (ADR-014). The UI must show progress and offer "Stop and use best so far" at all times.
- The best solution must survive a Stop or limit even though OR-Tools `Solve` cannot be interrupted cleanly from Python.
- Idle RAM < 300 MB (NFR-5): OR-Tools must not stay resident.
- Run-numbering rules (DISCUSS): only requests that reach the optimizer create runs.
- Single user, single Uvicorn worker.

## Decision

### Transport (carried over from ADR-008)
- `POST /api/projects/{project_id}/plan-runs` returns 202 `{job_id}`. Synchronous refusals create no job and no run:
  - missing anchor -> 422;
  - active job for the project -> 409;
  - routing engine not ready -> 503 "Routing engine not ready - nothing was changed".
- `GET /api/plan-jobs/{job_id}` is polled every 500 ms. `POST /api/plan-jobs/{job_id}/stop` stops a job.
- **"Re-optimise (ignore previous result)"** (D74): `POST /api/projects/{project_id}/plan-runs?ignore_memo=true` starts the same job lifecycle but skips the fingerprint memo and solves afresh to the full budget. It creates a new numbered run and leaves earlier runs untouched.

### Job states
```
queued -> snapping -> computing_legs -> checking_reachability -> solving -> finalising -> done
any state before solving  -- stop / feasibility limit / provider failure -->  cancelled | timed_out | refused   (no run; legs kept)
checking_reachability     -- unreachable item -->  done (Failed run, item named)                (ADR-016)
solving                   -- budget used up | optimisation limit | stop -->  finalising (best incumbent)
solving                   -- no valid incumbent at feasibility limit -->  done (Failed run, reason "timeout")
solving                   -- stop with no valid incumbent -->  done (Failed run, reason "stopped before a valid route was found")
solving                   -- feasibility limit WITH a valid incumbent -->  stays solving (continues to budget / optimisation limit / stop)
finalising                -- stop -->  ignored (finalising is short and not stoppable; poll shows stoppable=false)
finalising                -- guard fails on the chosen (last) incumbent -->  done (Failed run, reason "internal invariant violation"); NO fallback to an earlier incumbent
```
(Revision 2 rows from review L-2. Not falling back to an earlier incumbent is deliberate: a guard failure means a model or solver defect, which must surface rather than be masked.)
- Poll payload: `state`, `new_legs`, `cached_legs`, `legs_total`, `points_located`, `elapsed_s`, `incumbent` (unconfirmed count, objective, found_at_s), `stoppable`, `plan_run_id`, `message`.

### Solver child process (carried over from ADR-012, extended)
- `OrToolsTourSolver` spawns one child per solve (`multiprocessing`, `spawn`). `ortools` is imported only in the child.
- The child registers an at-solution callback and **streams every improving incumbent** through the pipe: order, unconfirmed count, retrace count, objective, elapsed.
- The parent keeps the **last valid incumbent**. On Stop, the optimisation limit or the feasibility limit, the parent stops reading, kills the child (SIGTERM, then SIGKILL after 2 s), and finalises with the last incumbent (or fails as above). When the budget is used up, the child sends `final` and exits normally.
- **Child dies with its parent**: on Linux the child sets `PR_SET_PDEATHSIG(SIGKILL)`, and a watchdog thread in the child exits on pipe EOF (this also covers macOS and dev).
- The guard (ADR-009) runs in the parent on the chosen incumbent.

### Ownership
`PlanJobRegistry` (application) holds jobs in memory, runs them on a bounded thread executor (max 1 job per project, max 2 overall), and keeps finished jobs for 10 minutes. A process restart loses running jobs: no run exists, cached legs remain.

### Gold tests
- Kill the parent mid-solve: the child is gone within 3 s.
- Stop after N incumbents: the run uses incumbent N, `reproducible=false`, labelled.
- Feasibility limit with zero incumbents: Failed run "timeout".
- Optimisation limit: labelled "not fully optimised".
- Stop during leg fetch: no run, legs cached.
- All are driven by the Mock latency plan and a test solver stub that emits scripted incumbents.

## Alternatives considered
- **In-process solve in a thread**: no hard kill and no reliable incumbent capture on Stop; OR-Tools stays resident; possible GIL stalls of polling.
- **Warm solver process pool**: OR-Tools resident at idle (NFR-5).
- **Persistent job queue / SSE** (as in ADR-008): unnecessary for one user.
- **Ask the child to stop cooperatively**: OR-Tools offers no safe cross-process interrupt; the callback could poll a flag, but kill + last incumbent is simpler and equally deterministic for what is returned.

## Consequences
- Positive: Stop and both limits always return a well-defined result; a solver crash or hang cannot take the API down; idle RAM excludes OR-Tools.
- Negative: about 0.5-3 s spawn overhead per solve (budgeted in ADR-014); incumbent streaming adds a small IPC cost per improvement.

## Amendment (DEVOPS, D93/D94) — 2026-11-02
DV-2, accepted by the user. Jobs stay in memory as decided above. In addition, when a job reaches a terminal state the application writes **one append-only `plan_job_log` row** (under the single write lock): job id, project, start/end, terminal state, plan run id (if any), item/leg/point counts (`legs_new`, `legs_cached`, `points_new`), `second_pass_pairs`, `retried`, `memo_hit`, `ignore_memo`, `stage_ms`, solver solutions and incumbents, reproducibility and "not fully optimised" reason, Unconfirmed/retrace counts, `provider_id`, `app_version`. Synchronous refusals (422/409/503) still create no job and are only logged. The state machine and run-numbering rules are unchanged. The row feeds `GET /api/diagnostics` (DV-3) and the KPI contracts (`docs/product/kpi-contracts.yaml`).
