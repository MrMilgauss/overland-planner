# Spike findings — overland-route-planner-mvp

## SPIKE-1R — solver on the Pi (2026-11-01)

**Verdict: WORKS.** Neither kill criterion fires.

- **K1 not met (pass):** `solution_limit = 10000` gives solve p95 **47.6 s (I1)** and **21.6 s (I2)** on the Pi (N=30 each). Road km is within **0.00% (I1)** and **2.57% (I2)** of the 30-min reference. With two-phase weighting: p95 47.4 s / 35.6 s, gaps 0.00% / 0.28%.
- **K2 not met (pass):** first valid I2 route arrives **0.22 s** after the solve request (p50; max 0.30 s, N=30), spawn and import included.

Probe question answered: yes. On the Pi, OR-Tools 9.15 meets p95 ≤ 55 s within 10% of the reference for the 60-item one-way directional instance, including forbidden arcs, lexicographic Unconfirmed weighting and exit-side retrace arcs. The count-based stop is deterministic: orders are bit-identical across 30 repeats and between Pi and Mac.

### Setup

- Host: Raspberry Pi 5 Model B Rev 1.1, 4 cores, 16,218 MB RAM (~12 GB available), kernel 6.18.33+rpt-rpi-2712, cgroup v2, Docker 29.5. Household services running throughout (load average 0.8–1.3).
- Container: `docker run --rm --init --cpus 2 --memory 1g`.
- Base image: `python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337` (arm64, Python 3.12.16).
- `ortools==9.15.6755` (latest on PyPI, 2026-11-01).
- Reference host: Mac, Apple M1 (8 cores), native Python 3.12.13 venv, same ortools.
- Model:
  - 62 nodes: Start, 40 tracks, 20 POIs, End.
  - One vehicle, start node 0, end node 61, all nodes mandatory, no disjunctions.
  - Cost matrix via `RegisterTransitMatrix`; None arcs removed with `NextVar(i).RemoveValue(j)`.
  - First solution `PATH_CHEAPEST_ARC`, then `GUIDED_LOCAL_SEARCH`, stopped by `solution_limit`. `time_limit` 1800 s as safety net only, never hit.
- Weights (ADR-016): `W2 = (N+1)·max_c + 1`, `W1 = (N+1)·(W2 + max_c) + 1`. I1: W1 = 850,781,547, W2 = 13,504,469, max_c = 217,814. I2: W1 = 900,516,645, W2 = 14,293,915, max_c = 230,547.
- Retrace arcs (ADR-017): cost = `W1·(1 + unconf(entry→entry)) + W2 + len(t) + RETRACE_PENALTY_M + c(entry(t)→entry(j))`, offered for every track t and successor j whose exit pair is None and whose entry pair exists.
- Instances: seeded (`GEN_SEED = 20261101`), 68 real Western Alps places, haversine × 1.3, integer metres. Track exits 2–40 km from entry at seeded bearing; track length = straight-line × 1.4.
  - **I1** (dense): 3,660 required pairs, all Confirmed.
  - **I2** (sparse): 288 None pairs (5% + dead ends), 107 Unconfirmed; dead-end tracks "Col du Mont Cenis" and "Crissolo" (no exit legs); 231 retrace pairs fetched (second pass) → 218 retrace arcs, 70 forbidden arcs.
  - Both pass the reachability check.
- Reference: 30-minute wall-clock GLS on the Mac. I1 lexicographic: 901,920 solutions, 1,020.017 km. I2 lexicographic (3,122,135 solutions) and two-phase (180 s + 1,800 s) reach the **same order** (sha `17f7072f15bf2b0f`, road 1,012.449 km) — reference is solid.

### Measurements (a)–(j)

Unless noted: Pi, `--cpus 2 --memory 1g`, lexicographic, `PATH_CHEAPEST_ARC`, `solution_limit` 10000.

| # | Measure | I1 (dense) | I2 (sparse) | N |
|---|---|---|---|---|
| (a) | Solve, budget 1,000 (calibration) | 4.57–4.83 s | 2.14–2.15 s | 3 |
| (a) | Solve, budget 3,000 (calibration) | 14.32–15.03 s | 6.33–6.46 s | 3 |
| (a) | Solve, budget 10,000 (calibration) | 44.81–47.58 s | 19.54–19.78 s | 3 |
| (a)/(d) | **Solve, budget 10,000 (chosen)** | **p50 46.23 / p95 47.56 / max 47.93 s** | **p50 19.75 / p95 21.58 / max 21.73 s** | 30 |
| (a) | Solve, two-phase, 10,000 (+ phase 1 ≤ 1,000) | p50 43.92 / p95 47.44 / max 48.39 s | p50 33.55 / p95 35.58 / max 36.63 s | 30 |
| (a) | Parent-observed wall (spawn → final) | p50 46.50 / p95 47.81 / max 48.22 s | p50 20.00 / p95 21.82 / max 21.99 s | 30 |
| (b) | Road km vs 30-min reference | 1,000: +0.74%; 3,000: 0.00%; 10,000: 0.00% | 1,000: +4.31%; 3,000: +2.57%; 10,000: **+2.57%** (two-phase +0.28%) | deterministic |
| (b) | Objective `c` vs reference | 0.00% | lexicographic +2.33%; two-phase +0.25%; U = 2, R = 2 always (lexicographic minimum) | deterministic |
| (c) | Order identity across repeats | 30/30 (sha `fb4c6f72…`) | 30/30 (sha `938136f7…`); two-phase 30/30 + 10/10 (sha `fb575f72…`) | 30 |
| (c) | Order identity Pi (aarch64 Linux) vs Mac (arm64 macOS) | identical at 1k/3k/10k, both weightings | identical at every budget, both weightings; first-solution sweep 260/260 | all |
| (d) | Budget with p95 ≤ 55 s | `solution_limit = 10000` (≈4.6 ms/solution I1, ≈2.0 ms I2; M1 ≈2.3× faster) | | |
| (e) | Spawn + `import ortools` | p50 0.185 / p95 0.208 / max 0.220 s | p50 0.182 / p95 0.212 / max 0.256 s | 30 |
| (e) | `import ortools` + `pywrapcp` alone | p50 0.079 / p95 0.091 / max 0.106 s | p50 0.078 / p95 0.103 / max 0.107 s | 30 |
| (f) | Child peak RSS | 55.7 MB (two-phase 58.7) | 55.2 MB (two-phase 58.2) | 30 |
| (f) | Probe-parent peak RSS (bare Python) | 24.7 MB | 25.7 MB (two-phase 27.2) | 30 |
| (f) | Container `memory.peak`, limit 1 GiB | max 51.3 MB (two-phase 54.5) | max 52.5 MB (two-phase 54.7) | per container |
| (f) | OOM kills | 0 | 0 | all |
| (f2) | Reachability check (pure Python BFS) | p50 0.003 s | p50 0.003 s | 30 |
| (f2) | Model build (child) | p50 0.007 / max 0.008 s | p50 0.008 / max 0.009 s | 30 |
| (f2) | **Reachability + build** vs ADR-014 1 s row | p95 0.011 s | p95 0.012 s | 30 |
| (g) | Improving incumbents streamed per solve | 63 (two-phase 170) | 65 (two-phase 147) | 30 |
| (g) | Stream latency, per-run median | p50 0.045 / p95 0.076 ms | p50 0.033 / p95 0.055 ms | 30 |
| (g) | Stream latency, per-run max | p50 0.19 / p95 2.2 / max 3.2 ms | p50 0.19 / p95 0.54 / max 4.1 ms | 30 |
| (g) | First incumbent after solve request (incl. spawn) | p50 0.218 / max 0.255 s | p50 0.215 / max 0.299 s (= K2) | 30 |
| (g) | Last streamed incumbent = final order | 30/30 | 30/30 | 30 |
| (h) | Lexicographic vs two-phase on I2, 10,000 | | lexicographic: +2.57%, p95 21.6 s; two-phase: **+0.28%**, p95 35.6 s; both U = 2, R = 2 | 30 + 30 |
| (i) | First-solution `ROUTING_FAIL` on 20 I2 variants (61–93 forbidden, 207–240 retrace arcs each) | | CHRISTOFIDES 20/20 fail; BEST_INSERTION 20/20 (also fails on I1); LOCAL_CHEAPEST_INSERTION 1/20; LOCAL_CHEAPEST_COST_INSERTION 1/20; **0/20** for AUTOMATIC, PATH_CHEAPEST_ARC, PATH_MOST_CONSTRAINED_ARC, SAVINGS, PARALLEL/SEQUENTIAL_CHEAPEST_INSERTION, GLOBAL_CHEAPEST_ARC, LOCAL_CHEAPEST_ARC, FIRST_UNBOUND_MIN_VALUE. Pi = Mac | 20 × 13 |
| (i) | Strategy quality, I2 lexicographic, 10,000 (road km vs ref) | | GLOBAL_CHEAPEST_ARC +0.71%; LOCAL_CHEAPEST_INSERTION +0.74%; PARALLEL/SEQUENTIAL_CHEAPEST_INSERTION +0.82%; LOCAL_CHEAPEST_ARC +0.92%; SAVINGS +1.62%; PATH_CHEAPEST_ARC / AUTOMATIC / PATH_MOST_CONSTRAINED_ARC +2.57%. Time ±8% | 1 each |
| (j) | `kill -9` parent → child gone | Pi with `PR_SET_PDEATHSIG`: 0.9 ms (2/2); Pi watchdog only: 31 ms; Mac watchdog only: 16 ms. All < 3 s | | 4 |

### Outputs for DESIGN

- **`SOLVER_BUDGET`**: OR-Tools `solution_limit = 10000`. Counts every accepted local-search solution, not only improving ones (~65 of 10,000 improve). Deterministic. Two-phase: phase-1 limit = budget / 10, phase-2 limit = 10,000. Wall-clock not used as stop.
- **Pinned ortools**: `ortools==9.15.6755`.
- **Base image**: `python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`.
- **Weighting mode**: **two-phase recommended** (ADR-016 fallback). Lexicographic also passes; choice, not requirement.
  - Big-W degrades GLS (ADR-016 trigger): lexicographic 2.57% off on I2, stagnates ~3,000→10,000 solutions, needs ~1.5 M to reach reference. Two-phase 0.28% off at 10,000.
  - Cost: two-phase slower on sparse (I2 p95 35.6 vs 21.6 s), equal on dense (I1 47.4 vs 47.6 s). Worst-case p95 ~47.5 s either way.
  - If lexicographic kept: first solution `GLOBAL_CHEAPEST_ARC` (+0.71% on I2, 0/20 fails).
- **Retrace penalty**: `RETRACE_PENALTY_M = 10,000` (ADR-017 default). `RETRACE_PENALTY_S` not exercised (distance objective only).
- **Memory**: child 55–59 MB, parent 25–27 MB, container peak ≤ 55 MB of 1 GiB, 0 OOM. The 1g `mem_limit` is dominated by the app, not the solver.
- **Spawn overhead**: p95 0.21 s, max 0.26 s (budget row 3 s).
- **Reachability + build**: p95 0.012 s (budget row 1 s).
- **Disjunction penalties (Q-U1)**: **not needed.** 9 of 13 strategies never fail on 20 sparse variants, default PATH_CHEAPEST_ARC included.

### Edge cases observed

- **Time per budget depends on instance**: ~4.6 ms/solution dense vs ~2.0 ms sparse (forbidden arcs shrink neighbourhoods). Dense all-Confirmed 60 items is worst case. More items → re-calibrate.
- **Pair count differs from brief**: 60-item one-way instance has 3,660 required pairs (60·59 + 60 + 60), not 3,423.
- **Strategies failing under forbidden arcs**: CHRISTOFIDES (all sparse variants), BEST_INSERTION (even I1), LOCAL_CHEAPEST_(COST_)INSERTION (1/20). Do not expose as configurable, or fall back on ROUTING_FAIL.
- **Two dead ends always resolved by retrace**: U = 2, R = 2 in every solution — the lexicographic minimum, so W1/W2 work as intended.
- **Cold first import on macOS 17.4 s** (first venv run); later 0.10 s. Pi container showed no cold spike (0.20 s first run).
- **Last streamed incumbent always equals final order** → parent can rely on it on Stop.
- **Kill semantics**: `--init` (tini) needed for PID-1 signal handling/reaping. PDEATHSIG ~1 ms; watchdog alone 31 ms.
- **Pi noise**: p95/p50 = 1.03 (I1), 1.09 (I2) with household services running. No run > 49 s.

### Design implications

- ADR-014 §3 confirmed: `solution_limit` deterministic across repeats and across aarch64 Linux / arm64 macOS. Fingerprint must include budget, strategy, weighting, ortools version (already listed).
- Solver path measures ~48 s (spawn 0.26 + build 0.012 + solve p95 47.6) vs 59 s budgeted (3 + 1 + 55) → ~7 s slack for SPIKE-2R rows. Alternative: raise SOLVER_BUDGET to ~11,500 (≈53 s on I1).
- ADR-016: adopt two-phase as default, or keep lexicographic + GLOBAL_CHEAPEST_ARC. Trade-off: code complexity vs +2.3% road km on sparse.
- ADR-015: streaming cheap (≤4 ms/message worst, 65–170 messages/solve), no throttling. Keep both PDEATHSIG and watchdog. Planner container `init: true`.
- OR-Tools ~60 MB at 60 items; NFR-5 idle RAM unaffected (child exits after solve).
- Solve seconds are host-specific; plans are not. New host only needs time re-calibration.

### Raw data

Probe code discarded at the promotion gate (2026-11-02, see wave-decisions.md). Raw data kept in `results/solver/`.

- `results/solver/all_runs.csv` — one row per run (702 rows), regenerated by `python3 analyze.py`.
- Pi JSONL `results/solver/pi/`: `pi_calib`, `pi_main_b10000`, `pi_h_twophase_30`, `pi_h_twophase`, `pi_firstsol`, `pi_jtest`.
- Mac JSONL `results/solver/`: `mac_ref_I1`, `mac_ref_I2`, `mac_ref_I2_twophase` (30-min references with incumbent curves), `mac_det`, `mac_h`, `mac_i_fullbudget`, `mac_firstsol`, `mac_jtest`.

Pi state after spike: `spike-solver` image removed, no spike containers; `~/spike-solver` deleted at the gate; `python:3.12-slim-bookworm` base image still present.

## SPIKE-2R — Valhalla on the Pi (2026-11-01)

**Verdict: WORKS.** No kill criterion fires. Two adapter-level findings must go into DESIGN (not kills, but they would produce wrong legs): costmatrix false nulls with the default config (fixed by one key), and permissive snapping onto footways.

- **K1 pass:** `ghcr.io/valhalla/valhalla-scripted:3.9.1-arm64` (sha256:f182f45e9e71cbe737e6c394d68808c67a7bd12e2a4cc47c4aba864de77ecdc6) runs natively on arm64.
- **K2 pass:** tile build 2,068 s (~34 min) under `--cpus 3 --memory 9g --memory-swap 9g`. It **ran at the cap under reclaim pressure**: cgroup `memory.peak` 9,663,676,416 B (= 9 GiB, page cache included), `memory.events max=80722`, `oom_kill=0`. No headroom: a bigger extract or OSM growth could OOM at 9 GiB.
- **K3 pass:** idle RSS 76 MB (10 min after fresh start) / 1,310 MB (10 min after load), limit 2 GB. Peak during matrix 1,588 MB VmRSS / 1,414 MB cgroup `memory.peak`, limit 4 GB. 0 OOM.
- **K4 pass:** cold 3,660-pair matrix (2 calls, concurrency 2) **p95 10.48 s, max 10.55 s** (N=30; cold = container restart + `drop_caches`). Threshold 75 s.
- **K5 pass:** every ladder option exists in 3.9.1 (binary strings + behavioural check where possible). `search_cutoff` works per location. `/locate`, 171, 442 shapes recorded. F-14 answered: `max_matrix_location_pairs` (2,500, inclusive) exists; `max_matrix_locations` does **not**.

Probe question answered: yes. Self-hosted Valhalla 3.9.1 on the Pi 5 serves the 60-item Alps workload under `mem_limit 4g`. Every routing stage is 6–100× under its ADR-014 row; end-to-end sum ~74 s vs 180 s.

### Setup

- Host: Pi 5, 16 GB, 4 cores; household services running throughout (load 0.5–1.5).
- Serving container: `docker run -d --name spike-valhalla --cpus 3 --memory 4g --memory-swap 4g -p 127.0.0.1:8002:8002 -v ~/valhalla-spike/custom_files:/custom_files`, env `serve_tiles=True use_tiles_ignore_pbf=True force_rebuild=False server_threads=2 build_admins=False build_time_zones=False build_elevation=False build_transit=False update_existing_config=False`. `server_threads=2` per ADR-013 §5; swap disabled (conservative).
- Build container (orchestrator): same image, `--cpus 3 --memory 9g --memory-swap 9g`, `server_threads=3 build_elevation=False build_admins=True build_time_zones=True build_transit=False`.
- Extracts: Geofabrik italy, switzerland, austria, france/rhone-alpes, france/provence-alpes-cote-d-azur (2026-11-01 snapshots), merged with osmium 1.15.0 into `alps.osm.pbf` (4.57 GB, 285 s).
- Tiles: `valhalla_tiles.tar` 4.4 GB, 2,245 tiles, mmapped; `tileset_last_modified` 1793560782.
- Client: stdlib Python 3.13 on the Pi host → 127.0.0.1:8002, ≤ 2 concurrent requests.
- Costing `4x4.v1` per ADR-013 §2: `use_tracks 1.0`, `exclude_unpaved false`, highways/tolls/ferry 0.5, `country_crossing_cost/penalty 0`, `ignore_oneways false`. Permissive variant: `ignore_access/closures/restrictions/non_vehicular_restrictions = true`. `search_cutoff` 250 m unless noted.
- Instance: SPIKE-1R generator (seed 20261101). 62 nodes, 102 distinct points (62 entries + 40 exits), 122 matrix endpoints (61 sources × 61 targets). One-way set **3,660 pairs**.
  - `/locate` 35 km cutoff, legal: 78 on_network (≤250 m), 17 near, 7 far. Permissive: 87 / 15 / 0.
  - K4 uses the legally snapped coordinate of all 122 endpoints (conservative: far points included, all 3,660 pairs requested).
- **Cold definition (finding):** `drop_caches` alone does not cool a running Valhalla — mmapped tile pages of a live process are not dropped (`pgmajfault` Δ 0). Reported cold = `docker stop` → `sync; drop_caches` → `docker start` → `/status` 200 → run (`pgmajfault` Δ ~750, ~225 MB tile read). `/status` answers 1.41–1.61 s after start.

### Measurements

| # | Measure | Result | ADR-014 row | N |
|---|---|---|---|---|
| 4/5 | Pair limit | `max_matrix_location_pairs` 2,500 inclusive: 50×50 OK; 61×41 = 2,501 → **error 150** "Exceeded max locations: 2500.000000". No `max_matrix_locations` key | | |
| 4/5 | Calls for 3,660 pairs | **2 rectangular calls**: 61×31 + 61×30 = 3,721 requested (61 wasted: 60 diagonal + Start→End) | ≥ 2 | |
| K4 | **Matrix, cold (restart + drop_caches)** | **p50 9.99 / p95 10.48 / max 10.55 s**; slowest call p95 10.47 s; pgmajfault Δ p50 754 (746–761) | 75 s | 30 |
| K4 | Matrix, drop_caches only | p50 9.63 / p95 9.90 / max 9.96 s; pgmajfault Δ 0 | | 30 |
| K4 | Matrix, warm | p50 9.59 / p95 9.86 / max 9.92 s | | 30 |
| K4 | Matrix with default `allow_second_pass=false` (wrong results) | 4.5 / 4.2 s per call, sequential | | 1 |
| K4 | Null cells in full matrix | 122 = 2 full source rows (exit of item 1 is a legal-costing island; exit of item 26 legally far, snapped onto an island). 40/40 sampled nulls confirmed by `/route` 442 | | |
| 6b | **Locate, 122 points, 250 m then 1,500 m (verbose), cold pipeline** | p50 0.29 / **p95 0.33** / max 0.33 s. Found 98/122 at 250 m, 115/122 at 1,500 m; one call each | 5 s | 30 |
| 6b | Locate, warm | p95 0.12 s | | 30 |
| 6c | **Second pass (right after first pass)** | p50 3.85 / **p95 4.04** / max 4.08 s | 15 s (P2 ≤ 700) | 30 |
| 6c | P2 / requested / calls | **P2 = 720**: 600 permissive retries (2 null rows + 8 access-restricted exits × 60) + 120 retrace pairs (2 tracks × 60). **Requested 732 (1.02 × P2)**, 2 parallel calls; 3rd (retrace-permissive) never needed | | |
| 6c | ms/pair | p50 5.35 / **p95 5.62** / max 5.67 ms (budget assumes ≤ 22 ms) | | 30 |
| 6c | Fixture content | 17 near endpoints (250–1,500 m) in first pass via snapped points; 8 exits snap ≤ 250 m only permissive (legal 870–2,706 m) → 480 access-restricted pairs. Permissive found 600/600; retrace legal 120/120 | ≥10 near, ≥20 restricted | |
| 6d | **Geometry, 61 legs `/route`, concurrency 2** | p50 0.67 / **p95 0.73** / max 0.88 s; slowest leg 0.11 s; 59/61 OK, 2 × 442 (island exit, consistent with matrix nulls) | 12 s | 30 |
| 6d | Geometry, isolated after cold first pass | max 0.77 s | | 10 |
| 6d | Single multi-point `/route` | not possible: `service_limits.auto.max_locations` = 20 | | |
| 6f | **Snapshot + pre-checks (SQLite, 60 items, 3,660 leg rows, 40 × 2,000-pt tracks, 74 MB DB)** | warm p50 0.094 / **p95 0.118** / max 0.120 s; cold max 0.109 s | 1 s | 30 / 10 |
| 6f | **Guard + assemble + persist (WAL, synchronous=FULL)** | warm p50 0.223 / **p95 0.235** / max 0.251 s; cold max 0.237 s | 3 s | 30 / 10 |
| 7 | Idle RSS 10 min after fresh start | VmRSS 76 MB; cgroup 57 MB | ≤ 2 GB | 1 |
| 7 | Idle RSS 10 min after load | VmRSS **1,310 MB** (anon 952, file 358); cgroup 1,204 MB; flat (`clear_reserved_memory=false`) | ≤ 2 GB | 1 |
| 7 | Peak during matrix | VmRSS max **1,588 MB** (anon 1,257) long-lived process (60 reps); cgroup `memory.peak` max 1,414 MB; after cold restart VmRSS 1,413 MB | ≤ 4 GB | 90 |
| 7 | Disk | `custom_files` 14 GB: tar 4.4 GB, tile dir 4.5 GB (unused at serve time when tar exists), PBF 4.57 GB, admins 33 MB, timezones 117 MB. `src/` extracts 4.3 GB | | |
| 8 | Torino (45.0703, 7.6869) → Susa (45.137, 7.050) | local 56.099 km / 3,342 s vs openstreetmap.org Valhalla (FOSSGIS) 56.487 km / 3,251 s → **−0.69 % distance**, +2.8 % time; `4x4.v1` identical route | ±15 % | 1 |

### Outputs for DESIGN

- **Image**: `ghcr.io/valhalla/valhalla-scripted:3.9.1-arm64@sha256:f182f45e9e71cbe737e6c394d68808c67a7bd12e2a4cc47c4aba864de77ecdc6` (Valhalla 3.9.1).
- **`valhalla.json` deltas** (original kept as `custom_files/valhalla.json.orig`):
  - `service_limits.auto.max_matrix_distance`: 400,000 → **2,000,000**;
  - `thor.costmatrix.allow_second_pass`: false → **true** — **mandatory** (edge case 1);
  - keep `service_limits.auto.max_matrix_location_pairs` = 2,500 / `VALHALLA_MAX_MATRIX_PAIRS` = 2,500;
  - serve with `update_existing_config=False` (True re-merges the config on start and rewrites `mjolnir.concurrency` as a string).
- **Extracts**: see Setup. Build with admins + time zones, no elevation; 2,245 tiles.
- **Stage timings vs ADR-014** (p95, Pi, cold pipeline):

| Stage | Measured p95 | Row |
|---|---|---|
| Request, snapshot, pre-checks | 0.12 s | 1 s |
| Point snapping | 0.33 s | 5 s |
| Confirmed matrix, cold | 10.48 s | 75 s |
| Second pass (P2 = 720) | 4.04 s | 15 s |
| Reachability + model build (SPIKE-1R) | 0.012 s | 1 s |
| Spawn + import (SPIKE-1R) | 0.21 s | 3 s |
| Solve (SPIKE-1R I1) | 47.56 s | 55 s |
| Guard + assemble + persist | 0.24 s | 3 s |
| Geometry | 0.73 s | 12 s |
| UI polling and render | not measured (budget kept) | 2 s |
| Reserve | | 8 s |

  **Measured sum 63.7 s; with UI 2 s + reserve 8 s = 73.7 s vs 180 s** (~106 s slack). Sum of p95s, so conservative.
- **RAM for `mem_limit`**: `4g` confirmed. Peak 1.59 GB VmRSS / 1.41 GB cgroup; steady state after use ~1.3 GB. Do not go below ~2g. Tile build needs the full 9 GiB and ran at the cap: keep `--memory 9g` minimum, consider 10–11 GB with serving stopped.
- **Matrix call plan**: 60 items one-way = 2 calls (61×31, 61×30) at concurrency 2. General: `ceil(|targets| / floor(2500 / |sources|))` calls.

### Edge cases observed

1. **Costmatrix false nulls with default config (most important).** With `thor.costmatrix.allow_second_pass=false`, **29/40 sampled null cells were routable** by `/route`; whole rows (exits of items 6, 28, 29) and a column (entry 55) null; one non-null cell 33.7 % shorter than `/route`. Cause: costmatrix hierarchy limits (e.g. local-level expansion only within 5 km). With `true`: 0/40 false nulls, 40/40 distances within 0.01 % of `/route`, ~2× matrix time (~10 s vs ~5 s). Without the fix the ladder would negatively cache false None pairs, trigger needless retraces, and could mark items Failed.
2. **One unsnappable location fails the whole matrix call** with error **170** ("Locations are in unconnected regions"), not 171 — for a far point, a near point at 250 m, and an access-restricted-only point. `/route` returns 171 for the same points. Adapter must send only legally snapped points in legal matrix calls, and map matrix 170 to "bad location", never "no connection".
3. **`/locate` never errors for an unsnappable point**: HTTP 200 with `"edges": [], "nodes": []`. Non-verbose has `correlated_lat/lon` but no distance; `verbose: true` adds `edges[].distance` (m). 122 locations in one call accepted (not bound by `max_locations` 20).
4. **Permissive snapping onto footways → 442.** With `ignore_access=true`, Loki snaps to car-inaccessible edges (Briançon → footway in Place d'Armes at 5.9 m instead of road at 52 m) → permissive Torino→Briançon 442 / null cell although a legal route exists. Legally snapped coordinates fix it (111.6 km). Rule for U1: use the **legally snapped coordinate** for every legally on_network endpoint; raw/permissive-snapped only for the off-network endpoint.
5. **Access-restricted endpoints misclassified by legal-only locate.** 9/102 points snap ≤ 250 m only under permissive costing (e.g. 22:exit 2,706 m legal vs 18 m permissive). ADR-016 §1 as written would class them near/far (km-long straight links or None) while a U1 leg exists. Classify with both legal and permissive `/locate` (< 0.2 s extra).
6. **`country_crossing_cost` is added to returned `time`** (600 adds exactly 600 s; 3,600 changes the route). Must stay 0 (ADR-013).
7. **Unknown costing options silently ignored** (`bogus_option_xyz` → 200, identical). Existence verified by binary strings + behaviour: `use_tracks` 1 vs 0 changed 29/40 track pairs; `exclude_unpaved` 9/40; `ignore_access` changes snapping/reachability; `ignore_restrictions`/`ignore_non_vehicular_restrictions` changed Briançon→Torino slightly (111.985 → 111.989 km); `ignore_closures` no observable effect without `traffic.tar`. Contract suite should pin the version via `/status`.
8. **Shapes.** Matrix cell `{from_index, to_index, time (int s), distance (km), cost, begin/end_heading, begin/end_lat/lon}`; null cell `{from_index, to_index, time: null, distance: null, cost: null}`; response has `"algorithm": "costmatrix"`. Errors `{"error_code": N, "error": "...", "status_code": 400, "status": "Bad Request"}`: 171 "No suitable edges near location", 442 "No path could be found for input", 170 "Locations are in unconnected regions…", 150 "Exceeded max locations: 2500.000000".
9. **Cold ≈ warm.** On NVMe the matrix is CPU-bound: cold adds ~0.6 s, reads ~225 MB of the 4.4 GB tar. Prefetch on import not needed.
10. **Second pass overstated.** Permissive retries resolved both null rows, so a real ladder would skip the 120 retrace pairs: real P2 = 600. 720 is an upper bound, still ~4× under the row.
11. **RSS not returned after load** (~1.3 GB until restart, `clear_reserved_memory=false`). Tile dir (4.5 GB) redundant at serve time when tar exists.
12. **Container user.** 3.9.1-scripted runs as root (uid 0); files it creates in `custom_files` are root-owned. Edits via `docker exec … jq … | sponge`.

### Design implications

- **ADR-013 §5**: add `thor.costmatrix.allow_second_pass: true` to build-service config deltas. Contract test: matrix null cell confirmed by `/route` 442 (fixture `matrix_confirmed_with_island_null_row`).
- **ADR-013 §6 error mapping**: matrix 170 = invalid location in batch. Pre-filter via `PointSnapper`; if 170 still occurs, split the batch / locate per point. Never record as None.
- **ADR-016 §1**: classify points with legal **and** permissive locate. For U1/U2 use legally snapped coordinates of on_network endpoints, never raw points.
- **ADR-014**: all SPIKE-2R rows far under budget (~106 s slack). `SOLVER_BUDGET` could rise ~3× (≈33,000 solutions in ~150 s on I1) if sparse quality justifies it; otherwise keep 10,000 and the slack as margin for larger projects / other hosts. Confirmed-matrix row could tighten to ~20 s.
- **ADR-007 / geometry**: per-leg `/route` ~11 ms → lazy geometry cheap. Legs to island points return 442; route those with the permissive variant.
- **Resources**: `mem_limit: 4g` OK. Build at 9 GiB is at its limit — if the extract grows, raise the build cap or build on the PC (K2 fallback).

### Raw data

Probe code discarded at the promotion gate (2026-11-02). Raw data kept in `results/valhalla/`, fixtures in `fixtures/`.

- `results/valhalla/`: `k4_coldrestart`, `k4_cold_dropcache`, `k4_warm`, `k4_trial` (.jsonl); `pipe_coldrestart`, `pipe_warm`, `pipe_cold_isolated_geom` (.jsonl); `s6f_warm.json`, `s6f_cold_{1..10}.json`; `idle_after_load.json`, `idle_fresh.json`, `options.json`; `matrix_batch{0,1}_resp.json`.
- `fixtures/` (redacted, synthetic public places only; `index.json`): matrix (Confirmed 5×5, island null row, permissive null cells, error 150, three 170 cases, U1 permissive success, full K4 request); route (geometry leg, 171 ×3, 442 ×4, U1 permissive OK, country-crossing 0/3600, Torino–Susa local + FOSSGIS); locate (non-verbose, verbose near, permissive access-restricted, far with empty edges); `/status`.
- `fixtures/torino_susa_fossgis.json`: the single request to `valhalla1.openstreetmap.de` (no personal data).

Pi state after spike: `spike-valhalla` removed, port 8002 closed, no spike containers/processes. Kept: `~/valhalla-spike/src`, `custom_files` (PBF, tiles, tar, sqlite, edited `valhalla.json` + `.orig`), `probe/` (deleted at the gate). Images present: `valhalla-scripted:3.9.1-arm64`, `python:3.12-slim-bookworm`, `debian:bookworm-slim`. Pre-existing exited containers untouched. ~120 `drop_caches` runs (consent D62); household containers stayed up.
