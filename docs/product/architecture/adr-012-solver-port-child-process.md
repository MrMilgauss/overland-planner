# ADR-012: Solver behind a TourSolver port, executed in a short-lived child process

## Status
**Superseded by ADR-015**, which keeps the TourSolver port and the per-solve child process and adds incumbent streaming, Stop, the revised limits and child-dies-with-parent (review B3).

Previously: Accepted (2026-11-01). Supported ADR-005 and ADR-008.

## Context
- D14: a mandatory spike may kill OR-Tools on the Pi ("alternative solver or heuristic"). The solver must therefore be swappable without touching the use cases.
- NFR-5: idle app RAM < 300 MB. Importing `ortools` in the main process keeps its native libraries resident (estimated tens of MB to about 100 MB, to be measured).
- The API must keep answering polls (500 ms) during a solve of up to 30 s. It is unconfirmed whether the OR-Tools Python `Solve` releases the GIL.

## Decision
- A `TourSolver` port (`solve(model, budget, ceiling_s) -> SolveResult`). `SolverModelBuilder` produces a solver-neutral model (node list, integer cost matrix, start index, end index, objective). It is the only input.
- `OrToolsTourSolver` runs each solve in a **short-lived child process** (`multiprocessing` with the `spawn` start method, one process per solve, killed if it exceeds the ceiling + 5 s). `ortools` is imported only in the child (import-linter contract: `ortools` only in `adapters.solver`).
- If the D14 spike shows that the spawn overhead threatens the 30 s p95 and that `Solve` releases the GIL, the adapter may switch to an in-process thread. That is an adapter-internal change, recorded as an ADR amendment.

## Alternatives considered
- **In-process solve in a worker thread**: lowest overhead, but OR-Tools stays resident (RAM) and polling may stall if the GIL is held.
- **Persistent process pool (1 warm worker)**: fast, but keeps OR-Tools resident at idle, which defeats the RAM purpose.
- **Call OR-Tools directly from the use case (no port)**: the solver could not be swapped after a D14 kill.

## Consequences
- Positive: idle RAM excludes OR-Tools; a solver crash cannot take the API down; the ceiling is enforced hard by process kill; the solver can be swapped (D14).
- Negative: about 0.5-2 s spawn + import overhead per solve on the Pi (included in the US-06 S1 p95; measured in the spike). A memo hit (ADR-005) skips it entirely.
