# C4 Diagrams — Overland Route Planner

Companion to `brief.md` (## Application Architecture), Revision 1. Mermaid C4 syntax. Every relationship is labelled with a verb.

## L1 — System Context

```mermaid
C4Context
  title System Context — Overland Route Planner (home LAN)
  Person(marco, "Marco (planner)", "Desktop browser on the home LAN")
  Person(giulia, "Giulia (household viewer)", "iPhone 390 px on the home Wi-Fi, read only")
  System(planner, "Overland Route Planner", "Compose stack on Raspberry Pi 5 (pi.example): planner app + self-hosted Valhalla. Imports tracks and POIs, plans a direction-safe itinerary, exports GPX 1.1")
  System_Ext(tiles, "Raster tile server", "OpenTopoMap (default) or OSM Standard")
  System_Ext(geofabrik, "Geofabrik", "Region catalogue and outlines (read by the planner), OSM extracts for the tile build (at the owner's chosen time)")
  System_Ext(nominatim, "OpenStreetMap Nominatim", "Place search by name (slice 12c, ADR-019; typed words only)")
  System_Ext(devices, "OsmAnd / Locus Map / Garmin", "Navigation apps and devices")

  Rel(marco, planner, "Plans trips and exports GPX with")
  Rel(giulia, planner, "Reads itineraries and maps in")
  Rel(marco, tiles, "Views map tiles from (browser)", "HTTPS")
  Rel(giulia, tiles, "Views map tiles from (browser)", "HTTPS")
  Rel(planner, geofabrik, "Reads the region catalogue and downloads OSM extracts from (the rebuild)", "HTTPS")
  Rel(planner, nominatim, "Searches place names in", "HTTPS/JSON, 1 request a second")
  Rel(marco, devices, "Loads exported GPX files into")
```

## L2 — Container

```mermaid
C4Container
  title Container Diagram — compose stack on the Pi
  Person(user, "Marco / Giulia", "Browser")
  System_Boundary(pi, "Raspberry Pi 5 — docker compose stack") {
    Container(spa, "Web UI", "Svelte 5 + Vite static SPA, MapLibre GL JS (runs in the browser)", "Projects, item list, results, warnings, diff, history, direction map, Stop")
    Container(api, "Planner application", "Python 3.12, FastAPI, Uvicorn (1 worker), mem_limit 1g", "JSON API, use cases, point snapping, leg ladder, plan jobs, guard, GPX export; delivers the SPA assets")
    Container(solverproc, "Solver child process", "Python + OR-Tools, one per solve", "Deterministic budget; streams incumbents to the parent")
    ContainerDb(db, "planner.sqlite", "SQLite WAL on volume planner-data", "Projects, items, history, warnings, plan runs, leg and point caches")
    ContainerDb(files, "Track file store", "Files on volume planner-data", "Originals by sha256; canonical/display points per direction version")
    Container(valhalla, "Valhalla", "Docker service, internal network only, mem_limit 4g", "Locate, matrix, route on Italy + Alps tiles")
    ContainerDb(tilesdb, "Valhalla tiles", "Volume valhalla-data", "Graph tiles, extract, valhalla.json")
    Container(build, "valhalla-build", "One-shot compose service (profile valhalla-build)", "Merges extracts and builds tiles")
  }
  System_Ext(tiles, "Tile server", "OpenTopoMap / OSM Standard")

  Rel(user, spa, "Uses")
  Rel(user, api, "Loads the SPA assets from", "HTTP, optional Basic auth")
  Rel(spa, api, "Calls JSON API, polls jobs, sends Stop to", "HTTP/JSON, 500 ms polling")
  Rel(spa, tiles, "Fetches raster tiles from", "HTTPS")
  Rel(api, solverproc, "Spawns and sends the solver model to", "multiprocessing pipe")
  Rel(solverproc, api, "Streams incumbents to", "multiprocessing pipe")
  Rel(api, db, "Reads and writes (single writer)", "SQLAlchemy 2")
  Rel(api, files, "Writes versioned track files to and reads them from", "atomic writes")
  Rel(api, valhalla, "Locates points, fetches matrices and leg routes from", "HTTP/JSON, max 2 concurrent")
  Rel(valhalla, tilesdb, "Memory-maps graph tiles from")
  Rel(build, tilesdb, "Writes built tiles to")
```

## L2 delta — slice 12c (road-map regions in the app)

```mermaid
C4Container
  title Container delta - slice 12c (the planner knows its map)
  Person(owner, "Owner / Marco / Giulia", "Browser")
  Container_Boundary(pi, "Raspberry Pi 5 - compose project overland") {
    Container(planner, "planner", "FastAPI", "Road-map, coverage and place-search routes; domain RoadMapCoverage")
    ContainerDb(queue, "overland_road-map", "Named volume", "request, running, progress, result files")
    ContainerDb(tiles, "overland_valhalla-data", "Named volume", "tilesets/<date>/ with tiles, road-map.json, outlines")
    Container(valhalla, "valhalla", "Docker service", "Routes; stopped during the build")
    Container(helper, "road-map-runner", "bash, user crontab, every minute", "Validates a request, runs the refresh at its time")
    Container(refresh, "tiles-refresh + valhalla-fetch/build", "bash, compose run", "Downloads, builds, switches, rolls back on failure")
  }
  System_Ext(geofabrik, "Geofabrik", "Catalogue, outlines, extracts")
  System_Ext(nominatim, "OSM Nominatim", "Place search")
  Rel(owner, planner, "Chooses regions and searches places through")
  Rel(planner, queue, "Writes requests to and reads progress from")
  Rel(planner, tiles, "Reads the served record from (read-only)")
  Rel(planner, valhalla, "Reads the served map date from", "HTTP /status")
  Rel(planner, geofabrik, "Reads the catalogue and outlines from", "HTTPS")
  Rel(planner, nominatim, "Sends the typed words to", "HTTPS, cached")
  Rel(helper, queue, "Takes requests from and writes progress to")
  Rel(helper, refresh, "Starts at the chosen time")
  Rel(refresh, geofabrik, "Downloads extracts and outlines from", "HTTPS")
  Rel(refresh, tiles, "Builds and promotes a new tileset in")
```

## L3 — Component: planning pipeline (inside "Planner application")

```mermaid
C4Component
  title Component Diagram — Planning pipeline
  Container_Boundary(app, "Planner application") {
    Component(router, "Plan runs router", "FastAPI", "POST plan-runs -> 202; GET plan-jobs/{id}; POST stop")
    Component(jobs, "PlanJobRegistry / PlanRequestJob", "application/planning", "State machine, limits, Stop, progress")
    Component(snapshot, "ProjectSnapshotReader", "port + SQLAlchemy adapter", "Frozen inputs incl. track versions and sha256")
    Component(snapper, "PointSnapper", "application/routing", "on_network / near / far per point")
    Component(resolver, "LegResolver (ladder)", "application/routing", "Confirmed -> Unconfirmed -> None; retrace pairs")
    Component(cache, "Leg and point caches", "port + SQLAlchemy adapter", "Level, reasons, negative entries")
    Component(counting, "CountingRoutingProvider", "adapters/routing", "Distinct pairs per job; points located")
    Component(reach, "ReachabilityChecker", "domain/planning", "Names unreachable items (FR-8.2)")
    Component(model, "SolverModelBuilder", "domain/planning", "Lexicographic weights, forbidden arcs, retrace arcs")
    Component(memo, "FingerprintMemo", "application/planning", "Reuses an identical successful run's order")
    Component(solver, "TourSolver / OrToolsTourSolver", "port + adapters/solver", "Child process; incumbents; budget and limits")
    Component(guard, "InvariantGuard", "domain/planning", "HC-1..HC-5, leg snapshot, retrace form")
    Component(assembler, "PlanRunAssembler", "domain/planning", "Itinerary, totals, report, warnings")
    Component(runs, "PlanRunRepository + UnitOfWork", "port + SQLAlchemy adapter", "One transaction per run")
    Component(events, "EventLog", "port + structlog adapter", "invariant.check, plan.run.completed")
  }
  Rel(router, jobs, "Starts, polls and stops jobs in")
  Rel(jobs, snapshot, "Reads frozen project inputs from")
  Rel(jobs, snapper, "Classifies new points with")
  Rel(jobs, resolver, "Resolves missing legs with")
  Rel(snapper, counting, "Locates points through")
  Rel(resolver, counting, "Requests matrices through")
  Rel(snapper, cache, "Stores snap results in")
  Rel(resolver, cache, "Looks up and stores legs in")
  Rel(jobs, reach, "Checks reachability with")
  Rel(jobs, model, "Builds the solver model with")
  Rel(jobs, memo, "Looks up the fingerprint in")
  Rel(jobs, solver, "Solves the model with (on a memo miss)")
  Rel(jobs, guard, "Verifies the chosen order with")
  Rel(jobs, assembler, "Assembles run results with")
  Rel(jobs, runs, "Persists the plan run through")
  Rel(jobs, events, "Emits run and guard events to")
  Rel(memo, runs, "Finds runs by fingerprint in")
```

## L3 — Component: RoutingProvider adapters

```mermaid
C4Component
  title Component Diagram — RoutingProvider port and adapters
  Container_Boundary(app, "Planner application") {
    Component(snapper, "PointSnapper", "application/routing", "Asks for snaps")
    Component(resolver, "LegResolver", "application/routing", "Asks for matrices (legal / permissive)")
    Component(geom, "LegGeometryService", "application/routing", "Lazy geometry for map and export")
    Component(counting, "CountingRoutingProvider", "decorator implementing the RoutingProvider port", "Counts distinct pairs per job and points located")
    Component(registry, "ProviderRegistry", "bootstrap", "Selects the adapter from ROUTING_PROVIDER")
    Component(valad, "ValhallaRoutingProvider", "adapters/routing, httpx", "4x4.v1 costing; batches <= 2,500 pairs; retries on 5xx/timeouts only; error mapping")
    Component(mock, "MockRoutingProvider", "adapters/routing", "Haversine x 1.3; scripted levels, snap classes and faults")
    Component(later, "Hosted adapter (later)", "adapters/routing", "e.g. OpenRouteService; same port and contract suite")
  }
  Container(valhalla, "Valhalla service", "compose, internal network")

  Rel(snapper, counting, "Locates points through")
  Rel(resolver, counting, "Requests matrices through")
  Rel(geom, counting, "Requests leg routes through")
  Rel(registry, counting, "Wraps the selected adapter in")
  Rel(counting, valad, "Delegates to (ROUTING_PROVIDER=valhalla)")
  Rel(counting, mock, "Delegates to (ROUTING_PROVIDER=mock)")
  Rel(counting, later, "Delegates to (future config value)")
  Rel(valad, valhalla, "Calls /locate, /sources_to_targets, /route, /status of", "HTTP/JSON")
```

The application sees only the `RoutingProvider` port; `CountingRoutingProvider` implements it and wraps one concrete adapter. Probe calls go straight to the adapter and are never counted.
