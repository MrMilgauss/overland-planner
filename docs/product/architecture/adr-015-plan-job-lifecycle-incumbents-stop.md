# ADR-015: Plan job lifecycle — limits, Stop, incumbent streaming, solver child process

## Status
Accepted (2026-11-01). Parameters measured by SPIKE-1R (2026-11-01; spike/findings.md: streaming, kill, spawn, child RSS). **Final-gate amendment** D122, D130, D133, D136 (2026-11-02). **Amendment 3** (slice 03b: table of endings D227, child time limit D228; 2026-11-11). The Stop semantics were confirmed by the user (D60). Supersedes ADR-008 and ADR-012. Resolves review B3.

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
finalising                -- stop -->  ignored (finalising is short and not stoppable; poll shows stoppable=false)   [final gate D136: Stop returns 200 idempotently with the incumbent being written]
finalising                -- guard fails on the chosen (last) incumbent -->  done (Failed run, reason "internal invariant violation"); NO fallback to an earlier incumbent
```
(Revision 2 rows from review L-2. Not falling back to an earlier incumbent is deliberate: a guard failure means a model or solver defect, which must surface rather than be masked.)
- Poll payload **[field names superseded by the final-gate amendment D130: `legs_new`, `legs_cached`, `points_new`]**: `state`, `new_legs`, `cached_legs`, `legs_total`, `points_located`, `elapsed_s`, `incumbent` (unconfirmed count, objective, found_at_s), `stoppable`, `plan_run_id`, `message`.

### Solver child process (carried over from ADR-012, extended)
- `OrToolsTourSolver` spawns one child per solve (`multiprocessing`, `spawn`). `ortools` is imported only in the child.
- The child registers an at-solution callback and **streams every improving incumbent** through the pipe: order, unconfirmed count, retrace count, objective, elapsed.
- [Superseded by Amendment 3 for the order of reading and the child's end.] The parent keeps the **last valid incumbent**. On Stop, the optimisation limit or the feasibility limit, the parent stops reading, kills the child (SIGTERM, then SIGKILL after 2 s), and finalises with the last incumbent (or fails as above). When the budget is used up, the child sends `final` and exits normally.
- **Child dies with its parent**: on Linux the child sets `PR_SET_PDEATHSIG(SIGKILL)`, and a watchdog thread in the child exits on pipe EOF (this also covers macOS and dev).
- The guard (ADR-009) runs in the parent on the chosen incumbent.

### Ownership
`PlanJobRegistry` (application) holds jobs in memory, runs them on a bounded thread executor (max 1 job per project, max 2 overall; **one solver child at a time**, final gate D133), and keeps finished jobs for 10 minutes. A process restart loses running jobs: no run exists, cached legs remain.

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

## Amendment (final gate, D122, D130, D133, D136) — 2026-11-02
Review findings R-02 (UI-7), R-10, R-15, R-18. Additions to the state table and ownership; earlier rows are unchanged unless marked.

**Additional state rows (D122).**
```
solving  -- child finishes normally (final) with NO valid incumbent (e.g. OR-Tools ROUTING_FAIL)   [refined by Amendment 3: "no route" only after a normal end]
             -->  done (Failed run, reason no_valid_route_found), immediately; the job does not wait for the feasibility limit
solving  -- child exits abnormally (crash, OOM kill, non-zero exit, pipe EOF without final), no valid incumbent   [Superseded by Amendment 3: only without a usable final]
             -->  done (Failed run, reason optimizer_failed)
solving  -- child exits abnormally WITH a valid incumbent   [Superseded by Amendment 3: only without a usable final]
             -->  finalising with that incumbent, labelled "not fully optimised (optimizer_failed)", reproducible=false
```
- The guard still runs on the incumbent; a guard failure gives Failed "internal invariant violation" as before.
- `optimizer_failed` logs `plan.job.finished` with the child's exit code/signal; the run-numbering rule is unchanged (solver-side outcomes create a numbered run).
- User-facing texts are the product owner's (OD-5 covers the limit cases). Reason codes are fixed here: `timeout`, `stopped`, `no_valid_route_found`, `optimizer_failed`, `internal_invariant_violation`, `unreachable`.
- Gold tests added: scripted child returning `final` with no incumbent -> Failed `no_valid_route_found` well before the limit; child killed with SIGKILL before/after its first incumbent -> Failed `optimizer_failed` / labelled run.

**Stop is idempotent (D136, replaces the row "finalising -- stop --> ignored").** `POST /api/plan-jobs/{job_id}/stop` always returns 200 with the current poll payload:
- in `finalising`: the job completes with the incumbent already being written; the response shows `state: finalising`, `stoppable: false`; repeated Stops change nothing;
- on a `done` job: returns the final payload (with `plan_run_id` if a run exists); no error;
- unknown or expired job id: 404 `{code: "not_found"}`.

**One solver slot (D133, replaces "max 2 overall" for the solve stage).** `PlanJobRegistry` keeps max 1 job per project and max 2 jobs overall, but only **one solver child runs at a time** (a process-wide slot). A job that reaches the solve stage while the slot is busy waits in state `waiting_for_optimizer`:
- it is stoppable; Stop while waiting -> `cancelled`, no run, legs kept (it has not started solving);
- the limits keep running from job start; the feasibility limit while waiting -> `timed_out`, no run, legs kept;
- `plan_job_log` records `solver_wait_s`; such jobs **count** in K5 (UD-3) and are reported separately.
Reason: the planner container is capped at 1 CPU (OD-9) and OR-Tools is single-threaded, so two children would each run at half speed and break the 55 s solve row; one child (55–59 MB measured) also closes F-6 (two children vs the 1g `mem_limit`).

**Amendment D209 (2026-11-05, user decision).** The "max 2 jobs overall" above is not enforced: there is no refusal for a further job. Each project still has at most one active job, and one solver child runs at a time; any other job waits in `waiting_for_optimizer`.

**Poll payload field names (D130).** One field-name table serves the poll payload and `plan_job_log`: `legs_new`, `legs_cached`, `legs_total`, `points_new` (replaces `new_legs`, `cached_legs`, `points_located` in the list above), plus `state`, `elapsed_s`, `incumbent {unconfirmed_legs, retraces, objective, found_at_s}`, `stoppable`, `plan_run_id`, `message`, `reason` (on terminal states). `incumbent.objective` is the reported objective (road + retrace km or time, without `RETRACE_PENALTY`; ADR-017 amendment). States in the payload are the snake_case names above, plus `waiting_for_optimizer`.

## Amendment 3 (slice 03b, D227, D228) — 2026-11-11
The two earlier amendments count as 1 (DEVOPS) and 2 (final gate). User decisions of 2026-11-10, built in slice 03b as `tour_outcome` and `read_tour_child` (D227, commit `5b416ee`) and `CHILD_TIME_LIMIT_MARGIN_S` (D228, commit `2197cfa`) in `adapters/solver/ortools_tour_solver.py`, then carried into the architecture documents at roadmap step 07-11. Review findings F3, F4, F6 of the slice-03 adversarial review. Commit ids are those of the 03b branch before push and may be restacked.

**Table of endings (D227), in the order the parent decides.** A complete valid final always wins, whatever the child's exit code, a Stop or a reached limit.

| What the parent saw | Outcome | Supersedes |
|---|---|---|
| a final whose order is a complete tour | the final order (budget used up), whatever the child's end, Stop or limit | the rows "child exits abnormally" (D122) and "kills the child ... finalises with the last incumbent" when a usable final exists |
| Stop came first, no usable final | the last valid incumbent labelled `stopped`, else Failed `stopped` | unchanged |
| the deadline that applies came first, no usable final | the last valid incumbent labelled `time_limit`, else Failed `timeout` | unchanged |
| a final without an order, and the child ended normally | Failed `no_valid_route_found` ("no route") | refines the D122 row: a final without an order is "no route" only after a normal end |
| anything else (abnormal end, no final, broken final) | the last valid incumbent labelled `optimizer_failed`, else Failed `optimizer_failed` with the exit code or signal | the two D122 rows, now only without a usable final |

- The child's exit code matters only without a usable final. It ended normally on exit code 0, or when it outlived the parent's reap wait after its final.
- **Read the pipe first.** On Stop or a reached limit the parent first reads what the child has already sent (without waiting, at most 1,000 messages), so a final already in the pipe is not lost. A child that keeps sending is cut off at 1,000.
- A message that cannot be read ends the reading; the child's end then decides.
- Poll, run flags and reason codes are unchanged (`stopped`, `time_limit`, `optimizer_failed`, `timeout`, `no_valid_route_found`).

**Child time limit (D228).** The child's own OR-Tools `time_limit` is the optimisation time left at spawn (`SolveDeadlines.remaining_s(found=True)`, never negative) plus 30 s (`CHILD_TIME_LIMIT_MARGIN_S`). The parent still ends the child first (SIGTERM, then SIGKILL after 2 s), so a live parent is unaffected. Reason: macOS has no `PR_SET_PDEATHSIG` and the child's parent-death watchdog thread needs the GIL, which the C++ search holds between solution callbacks; one child outlived its parent by about 5 days. On Linux (the Pi) `PR_SET_PDEATHSIG` still covers it. The golden order is unchanged. Test side: acceptance teardown ends the solve children a stopped planner left.

**Note (UI-DELIVER-7 item 3).** "Cached legs remain" after a lost job holds within one process until slice 05 persists the leg cache. Handled in slice 05, not here.
