# ADR-003: Frontend — Svelte 5 + Vite static SPA with MapLibre GL JS, served by FastAPI

## Status
Accepted (user decision, 2026-11-01). Resolves REQUIREMENTS Open Decision #4.

## Context
- The frontend must be lightweight and served from the same container. Desktop is primary; results and map must be readable at 390 px (US-05 S5, US-15 S4).
- The UI state is substantial: unified item list with filters, toggles, bulk selection, Stale badge, anchors, results, consideration report, warnings, diff, history and a map with click-to-add.
- Track direction must be visible: arrows and entry/exit markers (HC-1, FR-6.5).
- The JSON HTTP API is a mandatory driving port (D9).

## Decision
- A **Svelte 5** single-page app built with **Vite** into static assets (no SvelteKit server, no SSR). It is built in a `node` stage of the multi-stage Dockerfile and copied into the Python image. FastAPI serves it via `StaticFiles`. Node is never present at runtime. **[Corrected by Amendment 1: there is no SPA fallback to `index.html`.]**
- **MapLibre GL JS** for the map:
  - tracks drawn as line layers with a `symbol` layer using `symbol-placement: line` and a repeated arrow icon (pointing entry -> exit);
  - entry/exit circle markers;
  - road legs dashed or in a contrasting colour, and dashed grey with a "geometry unavailable" label when geometry cannot be fetched (ADR-007);
  - numbered stop markers and one combined S/E marker.
- The UI uses only the JSON API; it polls plan jobs every 500 ms (ADR-008).

## Alternatives considered
- **Plain TypeScript + Leaflet + arrow plugin**: the lightest option, but the UI state would grow into an ad hoc framework, and the arrow plugins (polylineDecorator, arrowheads) are lightly maintained. Kept as the fallback.
- **HTMX + Jinja2 + Leaflet (server-rendered)**: Python only, but it needs HTML fragment endpoints alongside the mandatory JSON API, so two representations to maintain; the map and list interaction still needs custom JS.
- **React or Vue + MapLibre**: works, but heavier runtime and tooling than one user needs.
- **Leaflet with Svelte**: viable; MapLibre was preferred for native line-placed symbols (arrows) and future vector/PMTiles support (ADR-004).

## Consequences
- Positive: small compiled bundle; reactive state; crisp, rotation-correct arrows at every zoom; pinch zoom on iPhone.
- Negative: a Node toolchain at build time; WebGL is required (available on all target browsers).
- Testing: Vitest for components; Playwright for 390 px viewport checks and the map/arrow checks (direction rendered from GeoJSON coordinate order, which the API supplies in canonical order).

## Amendment 1 (slice 03b, UI-DELIVER-7) — 2026-11-11
Corrects the Decision bullet on serving, per the slice-03 adversarial review (UI-DELIVER-7 items 1 and 2), built facts as of roadmap step 07-11.
- **No SPA fallback.** `adapters/http/web_page.py` mounts `StaticFiles(directory=WEB_DIST_DIR, html=True)` at `/`, after the API and health routes, and only when `index.html` exists. `html=True` serves `index.html` for a directory path and nothing else, so a deep path such as `/diagnostics` answers 404. The diagnostics page is therefore at **`#/diagnostics`** (hash route inside `index.html`). A fallback route would be a deliberate later change.
- **K2 "warning banner until acknowledged" is not built.** `docs/product/kpi-contracts.yaml` K2 asks for a red badge on the diagnostics page and a warning banner on the home page until acknowledged. Only the red badge exists. The banner needs an acknowledgement state (who acknowledged, when, persisted), which the UI has no place for. **Deferred to slice 12 (UI foundation).**

## Amendment 2 (slice 09, D255, D256) — 2026-11-17
- **MapLibre GL JS, pinned in package-lock.json, bundled by Vite (no CDN); version 6.19.0, not 5.x (D258: every 5.x release carries the critical advisory GHSA-jrc7-96c5-q579, fixed after 6.4.0).** Loaded lazily, so the main bundle stays at about 27 kB gzip and the map chunk is about 300 kB gzip. The run map is one Svelte component over a pure module that turns the geometry answer into MapLibre sources and layer styles; the pure module is what vitest tests (jsdom has no WebGL); Playwright with Chromium checks the rendered map. Styles: road Confirmed solid blue; Unconfirmed orange dotted with a "!" badge at its middle; retrace purple long-dash, no arrows, labelled "retrace"; track solid dark green with arrows (a `symbol` layer, `symbol-placement: line`, an arrow image drawn on a canvas at start-up, no sprite file); `unavailable` grey dashed with the label "geometry unavailable". Markers: numbered circles for stops, green dot for an entry, red square for an exit, one "S/E" marker for a round trip.
- **Map tiles (ADR-004 kept).** `GET /api/config/map` answers `tile_url`, `attribution`, `max_zoom` from `MAP_TILE_URL`, `MAP_TILE_ATTRIBUTION`, `MAP_TILE_MAX_ZOOM` (defaults: OpenTopoMap, its attribution, 17). A tile URL with a query parameter whose name contains `key`, `token`, `secret`, `signature` or `auth` refuses the start, naming `MAP_TILE_URL` and the parameter (never its value). The attribution control cannot be closed.
- **POI by map click (D256).** "Click on map" mode: a click opens a small name form at the click; a name adds the POI through the existing `POST /api/projects/{id}/pois`; Cancel or Escape adds nothing. A click within 12 px of a track's entry or exit marker takes that marker's exact coordinates. The plan is then Stale by the existing revision rule.
- The map is part of the plan page, below the itinerary, 60 % of the viewport height on a desktop and 70 % on a 390 px phone; pan and pinch zoom are MapLibre's own.
- **As built (step 10-06).** Deviations: MapLibre GL JS 6.19.0 instead of 5.x (D258); the stop numbers and the "retrace", "geometry unavailable" and "S/E" texts are HTML markers over the map rather than style layers; the arrow image is built from pixel data, not drawn on a canvas; and the plan panel reads its plan-run list again after a POI is added on the map, so the latest run shows Stale at once (D259). The three scenarios that wait for slice 08 stay `@pending`.

## Amendment 3 (slice 12, D264-D271) — 2026-11-18
- **One global stylesheet.** `web/src/app.css`, imported once in `main.ts`, holds the design tokens as CSS custom properties (colour roles, type scale, spacing, radii, focus ring, 44 px touch target) and the base look of every control. Components use tokens only. No CSS framework, no icon font, no runtime dependency. Alternatives rejected: a CSS framework (Tailwind, Pico: new build or runtime dependency for one user's page); per-component styles (today: the same rules in five files drift).
- **Theming.** Light by default; dark values under `@media (prefers-color-scheme: dark)`; `<meta name="color-scheme" content="light dark">`. No in-app switch. Text pairs >= 4.5:1, borders and focus >= 3:1, checked in CI. The map keeps one light palette in both themes (the tiles are light).
- **Layout.** The map is the workspace's main column (it no longer sits inside the plan panel, superseding Amendment 2's "below the itinerary"): side panel 360-420 px from 1024 px; map on top below 1024 px.
- **States and estimate.** One state badge in the plan area (No plan yet, Loading, Planning, Plan run #N, Failed, Stale). The run detail's `estimate` flag (from the stored provider id) shows an "estimate" pill and a map chip.
- **Map fold-ins.** Arrow size and spacing follow the zoom; the "retrace" label takes the first spot along its line clear of the stop numbers, or hides at that view.
- **K2 banner (closes Amendment 1's deferral).** Built on the home page; the acknowledgement is the acknowledged count in the browser's `localStorage`, no server state.
- Amendment 1's "no SPA fallback" still holds: routes stay hash routes.
- **As built (step 11-08).** Deviations: the export link reads "Export GPX of plan run #N" and the older run's export stays under a Failed run (D276, D208); the estimate pill sits inline at the start of the provider line; "Click on map" is a compact control on the map's top-left, under the estimate chip; arrow size runs 0.5-1.0 and spacing 160-80 px over zoom 8-13; the K2 acknowledgement is in `localStorage`, as designed. Slice 12 blocks in CI (job 2 for the API scenarios, job 7 for the Playwright ones).

## Amendment 4 (slice 12b, D283-D290) — 2026-11-19
- **Phases.** The project page shows one of three phases, derived in the page (pure `tripPhase.ts`, no server state): "Build the trip" (one trip list, one "Add", Start/End on a place's row, objective; main action "Plan the route"), "Planning" (progress, step words, best so far; "Stop and use best so far"), "Your route" (summary card, itinerary timeline, closed "Details"; main action "Export GPX", "Edit trip"). Supersedes Amendment 3's three side-panel groups and D272's button names.
- **Status words.** Loading, "Planning…", "Couldn't plan", "Out of date, plan again", "Route ready", "No plan yet"; "Previous route" heads an older ready run kept under a failed one (D208). The planner's messages stay verbatim: a ready run's `messages`, run number, provider line and Re-optimise are inside "Details"; failure words and notices stay in view (D285).
- **Map.** `TripMap` replaces `RunMap`: it draws the trip's items before any route, the run's route after; base map per ADR-004 Amendment 1 with a "Terrain" toggle (kept in `localStorage`); the route's layers always above the base style, including its labels; lines 4-7 px by zoom over a white casing; the itinerary and the map share the selected stop both ways.
- **Layout.** Below 1024 px the phase panel is one column under the map; the main action is pinned at the bottom (panel on a laptop, viewport below 1024 px).
- **As built (step 12-07).** Delivered as designed, with these deviations: track shapes before a plan show only their ends, as D288 states, no scenario asks for more; the 12b scenarios moved over the roadmap (the retrace scenario and the notices moved between steps 12-05 and 12-06, a place added on the map takes the page back to Build the trip, and the Objective select became the "Plan for" switch in 12-04); "Included" on an item was dropped and "Left out" shows for excluded items.
