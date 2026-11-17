<script lang="ts">
  // The map of a plan run under its itinerary (slice 09, ADR-003 Amendment 2). Everything that can be decided without
  // a screen is runMap.ts's; this draws it with MapLibre, loaded only when a run is shown, and tells a refusal in the
  // planner's words. The map settings are read once; the geometry again whenever the run shown changes.
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { failureText, readMapConfig, readRunGeometry } from './api';
  import { arrowImage, ARROW_IMAGE, buildRunMap, type MapConfig, type MapOverlay } from './runMap';

  let { planRunId }: { planRunId: string } = $props();

  let container = $state<HTMLDivElement | undefined>();
  let problem = $state('');
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
    const [config, geometry, maplibre] = await Promise.all([
      settingsOnce(),
      readRunGeometry(id),
      import('maplibre-gl'),
    ]);
    if (!current()) return () => {};
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
    if (plan.bounds) map.fitBounds(plan.bounds, { padding: FIT_PADDING, animate: false });
    for (const overlay of plan.overlays) {
      const anchor = NUMBERED.includes(overlay.kind) ? 'bottom' : 'center';
      new maplibre.Marker({ element: overlayElement(overlay), anchor })
        .setLngLat(overlay.lngLat)
        .addTo(map);
    }
    return () => map.remove();
  }

  $effect(() => {
    const id = planRunId;
    const frame = container;
    if (!frame) return;
    let active = true;
    problem = '';
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
  <div class="map" class:empty={problem !== ''} bind:this={container}></div>
</section>

<style>
  section {
    margin: 1rem 0;
  }
  .map {
    width: 100%;
    height: 60vh;
    min-height: 18rem;
  }
  .empty {
    display: none;
  }
  @media (max-width: 600px) {
    .map {
      height: 70vh;
    }
  }
  [role='alert'] {
    color: #8a1c1c;
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
