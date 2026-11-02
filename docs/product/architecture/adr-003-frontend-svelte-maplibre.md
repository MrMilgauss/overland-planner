# ADR-003: Frontend — Svelte 5 + Vite static SPA with MapLibre GL JS, served by FastAPI

## Status
Accepted (user decision, 2026-11-01). Resolves REQUIREMENTS Open Decision #4.

## Context
- The frontend must be lightweight and served from the same container. Desktop is primary; results and map must be readable at 390 px (US-05 S5, US-15 S4).
- The UI state is substantial: unified item list with filters, toggles, bulk selection, Stale badge, anchors, results, consideration report, warnings, diff, history and a map with click-to-add.
- Track direction must be visible: arrows and entry/exit markers (HC-1, FR-6.5).
- The JSON HTTP API is a mandatory driving port (D9).

## Decision
- A **Svelte 5** single-page app built with **Vite** into static assets (no SvelteKit server, no SSR). It is built in a `node` stage of the multi-stage Dockerfile and copied into the Python image. FastAPI serves it via `StaticFiles` with an SPA fallback to `index.html`. Node is never present at runtime.
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
