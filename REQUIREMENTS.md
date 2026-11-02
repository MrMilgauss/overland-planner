# Overland Route Planner — Requirements

> **For Claude Code:** This is the source of truth for the project. Read it fully before writing code. Items marked **HC** (hard constraints) are non-negotiable: never trade them off for simpler code or better metrics. Items listed under *Open Decisions* must be raised with the user before implementing anything that depends on them. Do not decide them silently.

---

## 1. Purpose

A self-hosted web application for planning overlanding holidays with a Land Rover Defender 90.

The user provides:
- **off-road tracks** (GPS tracks, usually GPX), and
- **points of interest** (cities, natural parks, exact coordinates).

The app produces a complete drivable itinerary that visits everything selected. It minimises road distance and backtracking between items, keeps a **fixed start and end point**, and **never alters the direction of any off-road track**.

The app runs as Docker container(s) on a Raspberry Pi on the home LAN and is used through a browser.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Track** | An off-road GPS track imported from a file. It has an ordered list of points; its **entry** is the first point and its **exit** is the last point. |
| **POI** | Point of interest: a single location (coordinates, or a geocoded place name). |
| **Item** | Generic term for a Track or a POI. |
| **Anchor** | The **Start** or **End** of the trip. Both are fixed by the user. |
| **Project / Trip** | A saved planning workspace containing items, settings and plan runs. |
| **Leg** | A road connection between two consecutive items, computed by the routing provider. |
| **Plan run** | One execution of the optimizer, with an immutable snapshot of its inputs and outputs. |
| **Routing provider** | The component that returns road distance, time and geometry between coordinates. |

---

## 3. Hard Constraints (non-negotiable)

### HC-1 — Tracks are directional
- Every track is driven **only** from its entry (first point) to its exit (last point), exactly as stored.
- The optimizer **must never reverse a track**, not even if reversing would shorten the route. Some trails are dramatically harder or impossible in the opposite direction.
- **Out-and-back retrace (exit side only, last resort; added 2026-11-01).** If no road leg (at any confidence level, see FR-5.8) leaves a track's exit B toward the next stop, but one leaves its entry A, the planner may propose driving the track A→B as stored and then driving back along the same track B→A, continuing from A. Example: tracks A→B and C→D become A→B→A→C→D. The track item itself is still driven entry→exit in full. The return B→A is a separate **retrace leg**, always flagged *Unconfirmed: retraces the trail backwards; check it is drivable in reverse*, and used only when no road option exists. The mirror case (entering a track backwards from its exit) is never proposed.
- The only way a track's direction can change is an **explicit user action** ("Reverse track direction"). This is intended for files recorded backwards. The action:
  - requires a confirmation dialog,
  - is recorded in the project history,
  - updates the track's stored canonical direction.
- The map must show track direction visually (arrows and entry/exit markers).
- Automated tests must assert that no generated plan ever traverses a track in reverse.

### HC-2 — Fixed start and end
- Every plan has exactly one **Start** and one **End**, chosen by the user.
- Start and End are always the first and last stops of the route. The optimizer reorders **only** the items between them.
- Start and End may be the same location (round trip).
- Start and End are POIs (a POI can be designated as an anchor). Whether a track may serve as an anchor is an *Open Decision* (see §10).
- The optimizer must refuse to run, with a clear message, if either anchor is missing.

### HC-3 — Explicit consideration list
- Every plan run outputs an **explicit list** of all items in the project, each clearly marked as:
  - ✅ **Included**: considered by the optimizer, with its position in the route,
  - ⛔ **Excluded**: present in the project but switched off by the user.
- The optimizer **never silently drops** an included item. If it can't place one (e.g. unroutable), the run reports the item and the reason as a failure.

### HC-4 — Incremental recalculation
- The user can toggle items on or off, add items or remove items, then press **Recalculate**. Nothing else has to be re-entered.
- Recalculation reuses everything already known (imported files, geocoding results, previously computed road legs). It computes only what's new (see §5.7).
- Each recalculation creates a new plan run. The user can see what changed from the previous run (see FR-6.4).

### HC-5 — Tracks are driven in full
- A track is never cut, shortened or partially driven by the optimizer. The plan includes the whole track from entry to exit.

---

## 4. Users & Usage

- Single user (plus household members) on the home LAN. No public exposure in v1.
- Typical trip: 5–40 tracks, 5–30 POIs, spanning one or more countries (mainly Italy and the Alps), one to several weeks.
- Primary usage is on a desktop browser. The results view should be readable on a phone.

---

## 5. Functional Requirements

### 5.1 Projects
- **FR-1.1** Create, rename, duplicate and delete projects.
- **FR-1.2** All project data persists across container restarts (mounted volume).
- **FR-1.3** Export and import a full project as a single file (e.g. ZIP with JSON + original track files) for backup and sharing.

### 5.2 Importing tracks
- **FR-2.1** Upload one or more track files at once: GPX (required). KML, KMZ and GeoJSON are nice to have.
- **FR-2.2** A single file containing several tracks or segments → each becomes a separate track. The user can merge segments instead if they belong together.
- **FR-2.3** Keep the original file unmodified. Store a parsed, simplified copy for display.
- **FR-2.4** On import, show per track: name, length, entry/exit coordinates, elevation gain/loss (if present), and an estimated duration (see FR-4.6).
- **FR-2.5** Detect loop tracks (entry ≈ exit within a configurable distance, default 200 m) and label them. A loop is still directional.
- **FR-2.6** Detect obviously broken data (single point, huge jumps between points) and warn the user.
- **FR-2.7** Explicit "Reverse track direction" action per HC-1.
- **FR-2.8** Per-track editable fields: name, notes, difficulty (free text or 1–5), estimated duration override.

### 5.3 Adding POIs
- **FR-3.1** Add a POI by:
  - entering coordinates (decimal degrees; DMS is nice to have),
  - searching a place name (geocoding), where the user picks from candidates,
  - clicking on the map.
- **FR-3.2** Per-POI editable fields: name, notes, category (e.g. city, park, viewpoint, campsite, fuel), and planned visit duration (default 0).
- **FR-3.3** Designate any POI as **Start** and/or **End** (HC-2).

### 5.4 Item list & selection (the "consideration list")
- **FR-4.1** One unified list of all items (tracks + POIs) in the project, filterable by type.
- **FR-4.2** Each item has an **Included** toggle. Anchors are always included and cannot be toggled off; they can only be reassigned.
- **FR-4.3** Bulk include/exclude (select several → toggle).
- **FR-4.4** Changing the list does not trigger optimization automatically. It marks the current plan as **stale** and enables **Recalculate**.
- **FR-4.5** Items can be removed from the project entirely, with a confirmation step.
- **FR-4.6** Estimated off-road duration for a track = length ÷ configurable average off-road speed (default 15 km/h), unless overridden per track.

### 5.5 Optimization
- **FR-5.1** Objective (selectable per project): **minimise total road distance** (default) or **minimise total road time**.
- **FR-5.2** The cost from item A to item B is the road leg from A's *exit point* to B's *entry point*. For a POI, entry = exit = its location. For a track, entry and exit are fixed by HC-1.
- **FR-5.3** The off-road length and duration of tracks are constant whatever the order. They are added to the totals but do not influence the order. Exception (2026-11-01): a retrace leg (HC-1, FR-5.8) is counted as ordinary off-road driving, with no separate breakdown, and it does depend on the order.
- **FR-5.4** Start and End are fixed (HC-2). All other included items are mandatory and must appear exactly once.
- **FR-5.5** Run time on the Raspberry Pi (revised 2026-11-01), all limits configurable:
  - **Target:** for 60 items, 95% of plans show the proposed route within **180 s**, end to end. The clock runs from pressing Calculate/Recalculate to the route on screen, including fetching all road legs not yet cached.
  - **Feasibility limit:** if no valid route has been found within **10 min**, the run aborts with a timeout error.
  - **Optimisation limit:** once a valid route exists, optimisation may continue until **30 min** after Calculate was pressed. The 30 min is measured from Calculate, not from the first valid route. If that limit is reached, return the best route found, labelled "not fully optimised".
  - **Stop:** a "Stop and use best so far" action is always available while a run is in progress.
- **FR-5.6** Deterministic for identical inputs (deterministic search budget plus reuse of the stored result), so recalculating with no changes gives the same plan. Exception (2026-11-01): the explicit action "Re-optimise (ignore previous result)" starts a fresh search and may return a different plan.
- **FR-5.8** **Road-leg confidence levels** (added 2026-11-01). Tracks often start or end away from paved roads, so road legs may use unpaved roads and forest tracks a 4x4 can reasonably drive (not open-terrain routing). The planner tries, in order:
  1. **Confirmed:** legal roads under the 4x4/car profile, forest tracks included.
  2. **Unconfirmed**, used only when level 1 has no connection:
     - the same request ignoring access, closure and restriction tags;
     - a short off-network link from the nearest road to a track entry or exit, or to a POI;
     - an out-and-back retrace (HC-1).
     These legs are shown in a distinct style, listed under Warnings as "check on the ground", and marked in the GPX leg name. Export is not blocked.
  3. **None:** no connection at any level.

  The optimizer first looks for an order with zero Unconfirmed legs. If none exists, it minimises the number of Unconfirmed legs, then the objective. A run fails only if some included item cannot be connected at any level; the failure names that item.
- **FR-5.7** Optional **manual pinning**: the user can lock an item's position or force "A before B". Phase 2.

### 5.6 Results
- **FR-6.1** Ordered itinerary table: position, item name, type, leg distance/time from previous, cumulative distance/time, track length/duration.
- **FR-6.2** Totals: road km, off-road km, total km, road time, off-road time, total time.
- **FR-6.3** **Consideration report** (HC-3): every project item with Included/Excluded status and its route position. Shown in the UI and included in exports.
- **FR-6.4** **Diff against the previous run**: which items were added or removed, which moved position, and the change in totals.
- **FR-6.5** Map view: road legs and off-road tracks in distinct styles, numbered stops, direction arrows on tracks, Start/End markers.
- **FR-6.6** History of plan runs per project. The user can view any past run and restore its item selection.
- **FR-6.7** Warnings section (see §5.8).

### 5.7 Recalculation & caching
- **FR-7.1** Cache road legs keyed by (rounded from-coordinate, rounded to-coordinate, routing provider, routing profile). Rounding is ~5 decimal places.
- **FR-7.2** On recalculation, request from the routing provider only the legs missing from the cache.
- **FR-7.3** Cache geocoding results.
- **FR-7.4** Cache entries can be invalidated per project (e.g. after changing the routing profile) or globally.
- **FR-7.5** Show progress during matrix computation: "computing 42 new legs / 380 cached".

### 5.8 Validation & warnings
- **FR-8.1** **Snap distance:** if a track entry/exit or a POI is more than X m from the nearest routable road (configurable, default 500 m), warn: "Track 'Passo X' entry is 1.2 km from the nearest road — check access".
- **FR-8.2** Unreachable item (e.g. an island without a ferry: no connection at any FR-5.8 level, in any order) → the run fails and names the item. A single missing pair does not fail the run if another order or confidence level connects every item.
- **FR-8.3** Duplicate items (same file imported twice, POIs within 50 m of each other) → warning on import.
- **FR-8.4** Overlapping or intersecting tracks → informational warning (no merging in v1).

### 5.9 Export
- **FR-9.1** A single GPX of the full trip: road legs as route/track segments, off-road tracks in original resolution, POIs as waypoints, all in itinerary order.
- **FR-9.2** Option: one GPX per item or per leg, zipped.
- **FR-9.3** Output must import cleanly into OsmAnd, Locus Map and Garmin devices. Use standard GPX 1.1 with no proprietary extensions required.
- **FR-9.4** Export the itinerary and consideration report as CSV and as a printable page.

### 5.10 Multi-day planning (Phase 2)
- **FR-10.1** Configurable max driving time per day and start-of-day time.
- **FR-10.2** Split the optimized route into days, respecting item durations.
- **FR-10.3** Optional overnight POIs (campsites/hotels). Splitting prefers to end days at these.
- **FR-10.4** Per-day GPX export.

### 5.11 Command-line interface (nice to have, Phase 2)
- **FR-11.1** A CLI inside the container to: import files into a project, toggle items, run a recalculation, export GPX. It's useful for scripting and debugging, and it uses the same core library as the web app.

---

## 6. Non-Functional Requirements

- **NFR-1 Platform:** runs on Raspberry Pi 4/5 (ARM64, 4–8 GB RAM). Images must be built for `linux/arm64`; `linux/amd64` should also work for development on a PC.
- **NFR-2 Deployment:** `docker compose up -d` brings up the whole stack. Configuration is via `.env`. Data lives on a named volume or bind mount.
- **NFR-3 Persistence:** SQLite for app data (single user, simple backups). Track files are stored on disk.
- **NFR-4 Security:** LAN-only by default. Optional basic auth via an environment variable. No secrets in images. API keys go in `.env`.
- **NFR-5 Resource use:** app idle RAM < 300 MB (excluding any self-hosted routing engine).
- **NFR-6 Resilience:** network failures toward external services produce clear errors and never corrupt project data.
- **NFR-7 Observability:** structured logs to stdout and a health-check endpoint.
- **NFR-8 Testing:** unit tests for parsing, the optimizer model and caching. Integration tests use a **mock routing provider**, so the suite runs offline with no API keys.

---

## 7. Suggested Architecture (adjustable — confirm with user before deviating significantly)

```
┌──────────── Browser (Web UI) ────────────┐
│  Map (Leaflet or MapLibre) · Item list   │
│  Results · Diff · Export                 │
└───────────────────┬──────────────────────┘
                    │ HTTP/JSON
┌───────────────────▼──────────────────────┐
│ Backend API (Python, FastAPI)            │
│  ├─ importers   (GPX/KML/GeoJSON)        │
│  ├─ geocoding   (pluggable)              │
│  ├─ routing     (pluggable provider)     │
│  ├─ leg cache   (SQLite)                 │
│  ├─ optimizer   (Google OR-Tools)        │
│  └─ exporters   (GPX, CSV)               │
└───────────────────┬──────────────────────┘
                    │
      ┌─────────────┴─────────────┐
      │ Routing provider (OPEN)   │
      │ hosted API or self-hosted │
      └───────────────────────────┘
```

- **Language/stack:** Python 3.12+, FastAPI, OR-Tools, gpxpy, SQLite (SQLAlchemy or plain), frontend kept lightweight (plain TS + Leaflet, or a small framework — Claude Code to propose).
- **Routing provider abstraction:** an interface such as:
  - `matrix(sources, destinations, profile) -> distances, durations`
  - `route(a, b, profile) -> geometry, distance, duration`
  - `snap(point) -> nearest_road_point, distance`

  Ship with:
  1. `MockProvider`: haversine distance × detour factor (default 1.3), for tests and offline development.
  2. At least one real provider. **Which one is an Open Decision (§10).** The design must make adding or swapping providers a config change, not a refactor.
- **Geocoding abstraction:** the same pattern. Nominatim or Photon are candidates.

### Optimization model (reference)
- Nodes: Start, End, each included POI, each included track (one node per track).
- For a track node, *arriving* means reaching its entry and *leaving* means departing from its exit. Cost(i→j) = road leg from exit(i) to entry(j). This makes the matrix **asymmetric**, and that's expected.
- No reverse variant of a track is ever created (HC-1).
- Fixed Start/End are set via OR-Tools' explicit start/end node configuration (HC-2).
- All included non-anchor nodes are mandatory (no disjunction penalties in v1). Exception (2026-11-01): penalties may be used only as an internal search aid on sparse matrices, behind config and only if the solver spike shows it is needed. A route that skips an included item is never accepted.
- Phase 2: time dimension for multi-day splitting, pinning constraints.

---

## 8. Phases & Acceptance Criteria

### Phase 1 — MVP
1. Docker compose stack runs on ARM64 and serves the web UI.
2. Create a project. Import GPX tracks. Add POIs by coordinates and by map click.
3. Set Start/End. Toggle items in and out.
4. Optimize with the mock provider and a self-hosted Valhalla routing engine on the Pi (decided 2026-11-01).
5. Results: itinerary table, totals, consideration report, map with direction arrows.
6. Recalculate after changes reuses cached legs (verified in logs/progress) and shows a diff.
7. Export full-trip GPX.

**Acceptance tests (must pass):**
- A-1: Given a track A→B where reversing would save distance, the plan still drives A→B. (HC-1)
- A-2: For any random input set, the first stop is Start and the last stop is End. (HC-2)
- A-3: The consideration report lists 100% of project items with correct status. (HC-3)
- A-4: Excluding one item and recalculating makes zero new routing requests. Adding one new POI requests only legs involving that POI. (HC-4)
- A-5: Exported GPX validates against the GPX 1.1 schema and opens in OsmAnd.
- A-6: Identical inputs produce identical plans. (Exception: an explicit "Re-optimise (ignore previous result)" may return a different plan; see FR-5.6 note.)
- A-7: Given track A→B whose exit has no road leg onward while its entry does, the plan drives A→B in full, then a retrace leg B→A flagged Unconfirmed, and never drives the track item B→A. (HC-1, FR-5.8)

### Phase 2
Geocoding search, multi-day splitting, pinning/ordering constraints, plan history restore, CLI, KML/GeoJSON import, snap-distance warnings if not already done.

### Phase 3
Optional hosted routing adapter (e.g. OpenRouteService) behind the same port, routing profiles (avoid motorways/tolls), project export/import, per-day exports and printable roadbook.

---

## 9. Out of Scope (v1)
- Routing *on* off-road tracks or discovering new tracks. Tracks are only ever the user's imported files.
- Legality checks for off-road tracks.
- Live navigation or turn-by-turn on the device.
- Multi-user accounts, public hosting.
- Weather, fuel range or ferry timetable integration.

---

## 10. Open Decisions (ask the user before implementing dependent parts)

> **Status 2026-11-01:**
> - #1 resolved: self-hosted Valhalla in the MVP; a hosted adapter may come later.
> - #2 resolved: anchors are POIs only.
> - #3 resolved: the default objective is distance.
> - #4 resolved: Svelte 5 + MapLibre.
> - #5 resolved: Pi 5, 16 GB.
> - #6 resolved: Nominatim, Phase 2.
>
> See `docs/product/architecture/`.

1. **Routing provider:** hosted API (e.g. OpenRouteService, GraphHopper cloud) vs self-hosted engine (e.g. Valhalla, OSRM, GraphHopper) vs both. The user has explicitly deferred this. Build the abstraction and the mock first.
2. **Can a track be the Start or End anchor?** (e.g. the trip starts with a trail). Default assumption: no, anchors are POIs.
3. **Default objective:** distance (current default) or time.
4. **Frontend framework** choice.
5. **Raspberry Pi model/RAM**, which affects whether self-hosted routing is viable.
6. **Geocoding provider** and usage policy compliance (Nominatim has strict rate limits).

---

## 11. Working Agreement for Claude Code
- Work phase by phase. At the end of each phase, summarise what's done and what the acceptance tests show.
- Write tests for HC-1 to HC-4 **before** or alongside the optimizer implementation.
- When a requirement is ambiguous, ask. Don't guess.
- Keep `README.md` updated with setup, `.env` options and how to deploy on the Pi.
