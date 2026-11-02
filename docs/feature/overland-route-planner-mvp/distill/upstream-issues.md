# Upstream issues found by DISTILL

Feature `overland-route-planner-mvp` | DISTILL (nw-acceptance-designer) | first pass 2026-11-02, closed in the final-gate fix round the same day. The reconciliation gate passed with 0 contradictions both times.

## Closed

| # | Gap (first pass) | Closed by | Applied in DISTILL |
|---|---|---|---|
| UI-1 | `/data` "not a mount point" rule would make bare-metal Linux runs degraded | DESIGN D121 (ADR-011 amendment): longest-prefix mount fstype; workspace `DATA_DIR` | D182: `MountTable.entries()`, workspace data folders |
| UI-2 | Job 2 did not build the web UI the WS checks | User UD-1, DEVOPS D162 | WS checks the real built page; no fallback |
| UI-3 | HTTP response/error shapes undesigned | DESIGN D130 (brief §5 "HTTP contract") | D183: envelope + enumerated codes, anchor enum |
| UI-4 | No source for entry/exit place names | OD-6, PO D152 | D109 kept (coordinates asserted, labels not) |
| UI-5 | Feasibility limit during the road look-up vs a numbered run | PO D157 (adopts D116) | Slice 03 scenarios for both outcomes |
| UI-6 | US-06a S2 limits violated the config ordering rule | PO back-propagated D116 | Given sets both limits |
| UI-7 | Solver ends with no solution before the limit | DESIGN D122 (`no_valid_route_found`, `optimizer_failed`) | Two new slice 03 scenarios |
| UI-8 | Newer DB check vs pre-migration copy order | DESIGN D129 (check first, nothing copied) | D185: outcome checked through the HTTP API, waiver W3 |
| UI-9 | DISTILL-introduced messages | OD-5, PO D151 | Messages applied verbatim, incl. the two time-limit messages and "X has no usable track" |
| UI-10 | Difficulty, merge, multi-file import with a bad file, Start+End-only plan | PO D149, D150, D154 (OD-3, OD-4) | New 07 and 02 scenarios |
| UI-11 | "One structured line" | PO D155 | D110 unchanged |
| UI-12 | `MountTable` not a DESIGN port | DESIGN D121 (brief §6 row) | Scaffold follows `entries()` |
| UI-13 | No "For Acceptance Designer" section in the brief | Not needed: brief §5 now carries the HTTP contract | - |
| UI-14 | Real GPX corpus missing | PO D158 (demo precondition) | Synthetic stand-ins stay until then |
| UI-15 | Brief §15 QEMU wording | DESIGN R-20 / DEVOPS | - |
| UI-16 | Diagnostics at slice 01a? | DEVOPS D178/D179: 00b `make diag` = docker stats + `/healthz`; diagnostics endpoint at 03-ops | Diagnostics scenarios stay in 03, 05, 06a, 11 |
| UI-17 | Runtime behaviour on an unexpected Valhalla version | DESIGN D128 (plan jobs refused, 503 `routing_engine_not_ready`) | New 06a `@technical` scenario |
| UI-18 | Property tests vs one OR-Tools child per solve | DISTILL D192 | Layer 1-2 in-memory composition through the `TourSolver` port; in-process solver hosting for properties is the crafter's call at slice 02; Hypothesis `dev` 100 on pre-push, `ci` 1,000 in CI |

## Open

| # | Severity | Item | Owner |
|---|---|---|---|
| UI-19 | Low | D156 renames the action to Calculate; DISTILL changed the DISCUSS message "Set the Start before optimizing" to "Set the Start before calculating" (US-04, slice 02) to keep one vocabulary. **CLOSED 2026-11-02: user confirmed "Set the Start before calculating".** | Product owner, before slice 02 GREEN |
