<script lang="ts">
  // The map of a plan run under its itinerary (slice 09, ADR-003 Amendment 2). Everything that can be decided without
  // a screen is runMap.ts's; this draws it with MapLibre, loaded only when a run is shown, and tells a refusal in the
  // planner's words. The map settings are read once; the geometry again whenever the run shown changes.
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { addPlace, failureText, readMapConfig, readRunGeometry } from './api';
  import PoiClickForm from './PoiClickForm.svelte';
  import {
    arrowImage,
    ARROW_IMAGE,
    buildRunMap,
    placeClicked,
    type MapConfig,
    type MapOverlay,
    type Place,
  } from './runMap';

  // `projectId` turns on the "Click on map" mode; `onplaceadded` tells the workspace to list the new place.
  let {
    planRunId,
    projectId,
    onplaceadded,
  }: { planRunId: string; projectId?: string; onplaceadded?: () => void } = $props();

  let container = $state<HTMLDivElement | undefined>();
  let problem = $state('');
  let clickMode = $state(false);
  let clicked = $state<(Place & { x: number; y: number }) | undefined>();
  let settings: Promise<MapConfig> | undefined;

  const NUMBERED = ['stop', 'start', 'end', 'start_end'];
  const FIT_PADDING = 48;

  function settingsOnce(): Promise<MapConfig> {
    settings ??= readMapConfig();
    settings.catch(() => (settings = undefined)); // a failed read is tried again with the next run
    return settings;
  }

  function overlayElement(overlay: MapOverlay): HTMLDivElement {
    const element = document.createElement('div');
    element.className = `run-marker ${overlay.kind}${NUMBERED.includes(overlay.kind) ? ' numbered' : ''}`;
    element.textContent = overlay.text;
    element.title = overlay.title;
    return element;
  }

  async function draw(
    id: string,
    frame: HTMLDivElement,
    current: () => boolean,
  ): Promise<() => void> {
    const [config, geometry, maplibre, worker] = await Promise.all([
      settingsOnce(),
      readRunGeometry(id),
      import('maplibre-gl'),
      // MapLibre finds its worker next to its own script, which the build does not copy: name it, so that it is a file
      // of the build (without it, no line is ever drawn).
      import('maplibre-gl/dist/maplibre-gl-worker.mjs?url'),
    ]);
    if (!current()) return () => {};
    maplibre.setWorkerUrl(worker.default);
    const plan = buildRunMap(geometry, config);
    const map = new maplibre.Map({
      container: frame,
      style: plan.style,
      maxZoom: config.max_zoom,
      attributionControl: false,
      dragRotate: false,
    });
    map.addControl(new maplibre.AttributionControl({ compact: false })); // always open: nothing to close
    map.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => map.addImage(ARROW_IMAGE, arrowImage()));
    // Read-only hook of the browser tests (tests/e2e/run-map.spec.ts): the map object, only when the page's URL has
    // `?e2e=1`, so that they can ask what was rendered. Nothing in the app reads or writes it.
    const exposed = new URLSearchParams(window.location.search).get('e2e') === '1';
    if (exposed) (window as unknown as { __overlandRunMap?: unknown }).__overlandRunMap = map;
    // The view is read-only on the frame, so that a test can turn a place into the pixel to click.
    const publish = (): void => {
      const centre = map.getCenter();
      frame.dataset.center = `${centre.lng},${centre.lat}`;
      frame.dataset.zoom = String(map.getZoom());
    };
    map.on('move', publish);
    map.on(
      'click',
      (event: { point: { x: number; y: number }; lngLat: { lng: number; lat: number } }) => {
        if (!clickMode) return;
        if (clicked) {
          clicked = undefined; // a click elsewhere closes the form
          return;
        }
        const entriesAndExits = plan.overlays
          .filter((overlay) => overlay.kind === 'entry' || overlay.kind === 'exit')
          .map((overlay) => ({ ...map.project(overlay.lngLat), lngLat: overlay.lngLat }));
        const place = placeClicked(
          event.point,
          [event.lngLat.lng, event.lngLat.lat],
          entriesAndExits,
        );
        clicked = { ...place, x: event.point.x, y: event.point.y };
      },
    );
    if (plan.bounds) map.fitBounds(plan.bounds, { padding: FIT_PADDING, animate: false });
    publish();
    for (const overlay of plan.overlays) {
      const anchor = NUMBERED.includes(overlay.kind) ? 'bottom' : 'center';
      new maplibre.Marker({ element: overlayElement(overlay), anchor })
        .setLngLat(overlay.lngLat)
        .addTo(map);
    }
    return () => {
      if (exposed) delete (window as unknown as { __overlandRunMap?: unknown }).__overlandRunMap;
      map.remove();
    };
  }

  async function addClicked(name: string): Promise<void> {
    if (!clicked || !projectId) return;
    await addPlace(projectId, { name, lat: clicked.lat, lon: clicked.lon });
    onplaceadded?.();
  }

  function toggleClickMode(): void {
    clickMode = !clickMode;
    clicked = undefined;
  }

  $effect(() => {
    const id = planRunId;
    const frame = container;
    if (!frame) return;
    let active = true;
    problem = '';
    clicked = undefined;
    const drawn = draw(id, frame, () => active).catch((error: unknown) => {
      if (active) problem = failureText(error);
      return () => {};
    });
    return () => {
      active = false;
      void drawn.then((remove) => remove());
    };
  });
</script>

<section aria-label="Map of the run">
  {#if problem}
    <p role="alert">{problem}</p>
  {/if}
  {#if projectId && !problem}
    <button type="button" aria-pressed={clickMode} onclick={toggleClickMode}>Click on map</button>
  {/if}
  <div class="frame" class:empty={problem !== ''}>
    <div class="map" bind:this={container}></div>
    {#if clicked}
      <div
        class="name-form"
        style:left="max(0px, min({clicked.x}px, 100% - 15rem))"
        style:top="min({clicked.y + 8}px, 100% - 9rem)"
      >
        <PoiClickForm add={addClicked} close={() => (clicked = undefined)} />
      </div>
    {/if}
  </div>
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .frame {
    position: relative;
    flex: 1;
    min-height: 0;
  }
  .name-form {
    position: absolute;
    z-index: 2;
  }
  button {
    margin-bottom: var(--space-2);
  }
  .map {
    width: 100%;
    height: 100%;
  }
  .empty {
    display: none;
  }
  :global(.run-marker) {
    font:
      600 0.8rem/1 system-ui,
      sans-serif;
    color: #111;
  }
  :global(.run-marker.numbered) {
    min-width: 1.5rem;
    padding: 0.2rem 0.35rem;
    border: 2px solid #fff;
    border-radius: 1rem;
    background: #1f2937;
    color: #fff;
    text-align: center;
    box-sizing: border-box;
  }
  :global(.run-marker.entry),
  :global(.run-marker.exit) {
    width: 0.8rem;
    height: 0.8rem;
    border: 2px solid #fff;
    box-sizing: border-box;
  }
  :global(.run-marker.entry) {
    border-radius: 50%;
    background: #16a34a;
  }
  :global(.run-marker.exit) {
    background: #dc2626;
  }
  :global(.run-marker.unconfirmed),
  :global(.run-marker.retrace),
  :global(.run-marker.unavailable) {
    padding: 0.1rem 0.35rem;
    border-radius: 0.3rem;
    background: rgb(255 255 255 / 0.85);
    white-space: nowrap;
  }
  :global(.run-marker.unconfirmed) {
    color: #ea580c;
    font-size: 1rem;
  }
  :global(.run-marker.retrace) {
    color: #7e22ce;
  }
  :global(.run-marker.unavailable) {
    color: #4b5563;
  }
</style>
