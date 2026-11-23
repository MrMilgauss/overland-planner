<script lang="ts">
  // The map of the trip (slice 09, ADR-003 Amendment 2; D288): the plan run on show when there is one, else the trip's
  // own items (a place a dot with its tag, a trail its entry and exit). Everything that can be decided without a screen
  // is runMap.ts's; this draws it with MapLibre, loaded only when there is something to show, and tells a refusal in the
  // planner's words. The map settings are read once; the geometry again whenever the run shown changes, the items
  // again whenever the trip changes.
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { untrack } from 'svelte';
  import { addPlace, failureText, readMapConfig, readRunGeometry, type Item } from './api';
  import PoiClickForm from './PoiClickForm.svelte';
  import { estimateMarker } from './planState';
  import { TerrainChoice } from './terrainChoice';
  import type { StyleSpecification } from 'maplibre-gl';
  import {
    adoptBaseStyle,
    arrowImage,
    ARROW_IMAGE,
    buildRunMap,
    buildTripMap,
    CREDIT_LAYER,
    DEFAULT_VIEW,
    DIMMED_PAINTS,
    stopBounds,
    stopOpacity,
    TERRAIN_LAYER,
    placeClicked,
    placeRetraceLabel,
    type ScreenBox,
    type MapConfig,
    type MapOverlay,
    type Place,
  } from './runMap';

  // `projectId` turns on the "Click on map to add" mode (the page's Add menu may put the map in it: `clickMode`);
  // `onplaceadded` tells the workspace to list the new place.
  let {
    planRunId,
    items = [],
    projectId,
    estimate = false,
    selectedStop = undefined,
    onselectstop,
    onplaceadded,
    canAdd = true,
    clickMode = $bindable(false),
  }: {
    planRunId?: string;
    items?: Item[];
    projectId?: string;
    estimate?: boolean;
    /** The stop selected on the page (D286): the map goes to it, rings its number and dims the other lines. */
    selectedStop?: number | undefined;
    /** A number marker pressed, or 'Show whole route' (undefined). */
    onselectstop?: (stop: number | undefined) => void;
    onplaceadded?: () => void;
    /** False while the trip is planned (it is read-only then): no "Click on map to add", clicks on the map add nothing. */
    canAdd?: boolean;
    clickMode?: boolean;
  } = $props();

  let container = $state<HTMLDivElement | undefined>();
  let problem = $state('');
  let clicked = $state<(Place & { x: number; y: number }) | undefined>();
  let settings: Promise<MapConfig> | undefined;
  let select: ((stop: number | undefined, fit: boolean) => void) | undefined; // the drawn map's, once it is drawn

  const marker = $derived(estimateMarker(estimate));

  const NUMBERED = ['stop', 'start', 'end', 'start_end'];
  const FIT_PADDING = 48;
  // Room on the right for the widest place tag (Start/End) beside a dot at the edge of the items' bounds.
  const ITEMS_FIT_PADDING = {
    top: FIT_PADDING,
    bottom: FIT_PADDING,
    left: FIT_PADDING,
    right: 112,
  };
  const STOP_MAX_ZOOM = 13; // a trail
  const ITEMS_MAX_ZOOM = 12; // one place alone is not zoomed in on to the street
  // Without a run the map is drawn afresh whenever the trip's items change; with one, the items do not matter.
  const itemsKey = $derived(planRunId ? '' : JSON.stringify(items));

  function settingsOnce(): Promise<MapConfig> {
    settings ??= readMapConfig();
    settings.catch(() => (settings = undefined)); // a failed read is tried again with the next run
    return settings;
  }

  function overlayElement(overlay: MapOverlay): HTMLDivElement {
    const element = document.createElement('div');
    element.className = `run-marker ${overlay.kind}${NUMBERED.includes(overlay.kind) ? ' numbered' : ''}`;
    if (overlay.kind === 'place' && overlay.text) {
      const tag = document.createElement('span');
      tag.className = 'place-tag';
      tag.textContent = overlay.text;
      element.append(tag);
    } else element.textContent = overlay.text;
    element.title = overlay.title;
    return element;
  }

  async function draw(
    id: string | undefined,
    tripItems: Item[],
    frame: HTMLDivElement,
    current: () => boolean,
  ): Promise<() => void> {
    const [config, geometry, maplibre, worker] = await Promise.all([
      settingsOnce(),
      id ? readRunGeometry(id) : Promise.resolve(undefined),
      import('maplibre-gl'),
      // MapLibre finds its worker next to its own script, which the build does not copy: name it, so that it is a file
      // of the build (without it, no line is ever drawn).
      import('maplibre-gl/dist/maplibre-gl-worker.mjs?url'),
    ]);
    if (!current()) return () => {};
    maplibre.setWorkerUrl(worker.default);
    const choice = new TerrainChoice();
    let terrain = choice.terrain();
    let adopted = false; // the light base map is the map's: its credit may show
    const plan = geometry
      ? buildRunMap(geometry, config, terrain)
      : buildTripMap(tripItems, config, terrain);
    const map = new maplibre.Map({
      container: frame,
      style: plan.style,
      maxZoom: config.max_zoom,
      attributionControl: false,
      dragRotate: false,
      ...(plan.bounds ? {} : DEFAULT_VIEW),
    });
    map.addControl(new maplibre.AttributionControl({ compact: false })); // always open: nothing to close
    // Terrain and the credit of the light base map follow the choice; while a style is being replaced the layers are not
    // there to set, and the next 'style.load' sets them again.
    const showTerrain = (): void => {
      try {
        map.setLayoutProperty(TERRAIN_LAYER, 'visibility', terrain ? 'visible' : 'none');
        const light = adopted && !terrain;
        map.setLayoutProperty(CREDIT_LAYER, 'visibility', light ? 'visible' : 'none');
      } catch {
        // see above
      }
    };
    const terrainButton = document.createElement('button');
    terrainButton.type = 'button';
    terrainButton.className = 'terrain-button';
    terrainButton.textContent = 'Terrain';
    terrainButton.setAttribute('aria-pressed', String(terrain));
    terrainButton.addEventListener('click', () => {
      terrain = !terrain;
      choice.choose(terrain);
      terrainButton.setAttribute('aria-pressed', String(terrain));
      showTerrain();
    });
    const terrainGroup = document.createElement('div');
    terrainGroup.className = 'maplibregl-ctrl maplibregl-ctrl-group terrain-control';
    terrainGroup.append(terrainButton);
    // Added before the zoom buttons, so that it stands above them in the top-right corner.
    map.addControl(
      { onAdd: () => terrainGroup, onRemove: () => terrainGroup.remove() },
      'top-right',
    );
    map.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
    // A style replaced (the light base map adopted) loses the arrow image: draw it again with every style.
    map.on('style.load', () => {
      if (!map.hasImage(ARROW_IMAGE)) map.addImage(ARROW_IMAGE, arrowImage());
      showTerrain();
    });
    // The light base map is fetched here, so that the planner's own style (never blank) stands until it has come, and
    // for good when it does not come: the route stays on the plain background (D287).
    void fetch(config.base_style_url)
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json() as Promise<StyleSpecification>;
      })
      .then((base) => {
        if (!current()) return;
        adopted = true;
        map.setStyle(base, {
          diff: false,
          transformStyle: (_previous, next) => adoptBaseStyle(plan.style, next, terrain),
        });
      })
      .catch(() => {
        // The light base map does not load: the route stays on the plain background, nothing to tell.
      });
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
        if (!clickMode || !canAdd) return;
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
    if (plan.bounds)
      map.fitBounds(plan.bounds, {
        padding: geometry ? FIT_PADDING : ITEMS_FIT_PADDING,
        animate: false,
        ...(geometry ? {} : { maxZoom: ITEMS_MAX_ZOOM }),
      });
    publish();
    const numbered: { element: HTMLElement; stops: number[] }[] = [];
    const retraces: {
      marker: { setLngLat(lngLat: [number, number]): unknown };
      element: HTMLElement;
      candidates: NonNullable<MapOverlay['candidates']>;
    }[] = [];
    for (const overlay of plan.overlays) {
      const anchor = NUMBERED.includes(overlay.kind) ? 'bottom' : 'center';
      const element = overlayElement(overlay);
      const placed = new maplibre.Marker({ element, anchor }).setLngLat(overlay.lngLat).addTo(map);
      if (overlay.candidates)
        retraces.push({ marker: placed, element, candidates: overlay.candidates });
      if (overlay.stops) {
        const stops = overlay.stops;
        numbered.push({ element, stops });
        element.addEventListener('click', (event) => {
          event.stopPropagation(); // not a click on the map
          onselectstop?.(stops[0]);
        });
      }
    }
    // The selection: the number's ring, the other lines dimmed, the fit and the way back (D286).
    let chosen: number | undefined;
    const wholeRoute = document.createElement('button');
    wholeRoute.type = 'button';
    wholeRoute.className = 'whole-route-button';
    wholeRoute.textContent = 'Show whole route';
    wholeRoute.addEventListener('click', () => onselectstop?.(undefined));
    const wholeRouteGroup = document.createElement('div');
    wholeRouteGroup.className = 'maplibregl-ctrl maplibregl-ctrl-group whole-route-control';
    wholeRouteGroup.hidden = true;
    wholeRouteGroup.append(wholeRoute);
    map.addControl(
      { onAdd: () => wholeRouteGroup, onRemove: () => wholeRouteGroup.remove() },
      'bottom-left',
    );
    let everDimmed = false;
    const dim = (): void => {
      if (chosen === undefined && !everDimmed) return; // nothing was ever dimmed: nothing to undo
      everDimmed = true;
      // While a style is being replaced the layers are not there to set; the next 'style.load' sets them again.
      for (const [layer, property] of DIMMED_PAINTS) {
        try {
          map.setPaintProperty(layer, property as 'line-opacity', stopOpacity(chosen));
        } catch {
          // see above
        }
      }
    };
    map.on('style.load', () => {
      if (chosen !== undefined) dim();
    });
    select = (stop, fit) => {
      chosen = stop;
      for (const { element, stops } of numbered)
        element.classList.toggle('selected', stop !== undefined && stops.includes(stop));
      dim();
      frame.dataset.selectedStop = stop === undefined ? '' : String(stop);
      wholeRouteGroup.hidden = stop === undefined;
      const bounds = stop === undefined || !geometry ? plan.bounds : stopBounds(geometry, stop);
      if (fit && bounds)
        map.fitBounds(bounds, {
          padding: FIT_PADDING,
          animate: false,
          ...(stop === undefined ? {} : { maxZoom: STOP_MAX_ZOOM }),
        });
      publish();
    };
    const first = untrack(() => selectedStop);
    select(first, first !== undefined);
    // A "retrace" label stands at the first candidate place whose box covers no stop number, and waits (hidden) until a
    // move leaves one clear (D270). Read from the page's own boxes, after every move.
    const keepClear = (): void => {
      const origin = frame.getBoundingClientRect();
      const numbers: ScreenBox[] = [...frame.querySelectorAll('.run-marker.numbered')].map((el) =>
        el.getBoundingClientRect(),
      );
      for (const { marker: placed, element, candidates } of retraces) {
        element.style.display = ''; // a hidden label has no size to measure
        const size = element.getBoundingClientRect();
        const spotOf = (fraction: number) =>
          candidates.find((candidate) => candidate.fraction === fraction)!.lngLat;
        const chosen = placeRetraceLabel((fraction) => {
          const at = map.project(spotOf(fraction));
          const [x, y] = [origin.left + at.x, origin.top + at.y];
          return {
            left: x - size.width / 2,
            right: x + size.width / 2,
            top: y - size.height / 2,
            bottom: y + size.height / 2,
          };
        }, numbers);
        if (chosen === 'hidden') element.style.display = 'none';
        else placed.setLngLat(spotOf(chosen));
      }
    };
    map.on('moveend', keepClear);
    keepClear();
    return () => {
      select = undefined;
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
    if (canAdd) return;
    clickMode = false; // read-only now: no mode and no name form left open
    clicked = undefined;
  });

  $effect(() => {
    const stop = selectedStop;
    select?.(stop, true);
  });

  $effect(() => {
    const id = planRunId;
    void itemsKey; // the trip changed: draw it again
    const frame = container;
    if (!frame) return;
    const tripItems = untrack(() => $state.snapshot(items)) as Item[];
    let active = true;
    problem = '';
    clicked = undefined;
    const drawn = draw(id, tripItems, frame, () => active).catch((error: unknown) => {
      if (active) problem = failureText(error);
      return () => {};
    });
    return () => {
      active = false;
      void drawn.then((remove) => remove());
    };
  });
</script>

<section aria-label="Map of the trip">
  {#if problem}
    <p role="alert">{problem}</p>
  {/if}
  <div class="frame" class:empty={problem !== ''}>
    <div class="map" bind:this={container}></div>
    <div class="overlay">
      {#if marker}
        <span class="chip" role="note" title={marker.note} aria-label={marker.note}
          ><span aria-hidden="true">{marker.glyph}</span>{marker.label}</span
        >
      {/if}
      {#if projectId && canAdd && !problem}
        <button type="button" class="click-mode" aria-pressed={clickMode} onclick={toggleClickMode}
          >Click on map to add</button
        >
      {/if}
    </div>
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
  .overlay {
    position: absolute;
    top: var(--space-2);
    left: var(--space-2);
    z-index: 2;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 0 var(--space-3);
    border: 1px dashed var(--color-warning-fg);
    border-radius: var(--radius-pill);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
    font-size: var(--text-sm);
    font-weight: 600;
  }
  /* The map keeps its light palette in both themes (D265): the control is a map overlay. */
  :global(.maplibregl-ctrl-group .terrain-button) {
    width: auto;
    min-width: 44px;
    min-height: 44px;
    padding: 0 0.75rem;
    border: 0;
    border-radius: 4px;
    background: white;
    color: black;
    font:
      600 0.9rem/1 system-ui,
      sans-serif;
  }
  /* Pressed: an accent fill, white text and an underline. Named with :not(:disabled) so that it outranks MapLibre's own
     hover and focus rule for the control group's buttons (a pale grey fill, which left white text unreadable). */
  :global(.maplibregl-ctrl-group button.terrain-button[aria-pressed='true']:not(:disabled)) {
    background: rgb(29 78 216);
    color: white;
    text-decoration: underline;
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
    color: black;
  }
  /* The stop selected on the itinerary or on the map: ringed in the accent colour (D286). */
  :global(.run-marker.numbered.selected) {
    box-shadow: 0 0 0 3px var(--color-accent);
  }
  :global(.maplibregl-ctrl-group .whole-route-button) {
    width: auto;
    min-width: 44px;
    min-height: 44px;
    padding: 0 0.75rem;
    border: 0;
    border-radius: 4px;
    background: white;
    color: black;
    font:
      600 0.9rem/1 system-ui,
      sans-serif;
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
  :global(.run-marker.place) {
    position: relative;
    width: 0.9rem;
    height: 0.9rem;
    border: 2px solid #fff;
    border-radius: 50%;
    background: #1f2937;
    box-sizing: border-box;
  }
  :global(.run-marker.place .place-tag) {
    position: absolute;
    top: 50%;
    left: 100%;
    margin-left: 0.2rem;
    padding: 0.1rem 0.35rem;
    border-radius: 0.3rem;
    background: #1f2937;
    color: #fff;
    transform: translateY(-50%);
    white-space: nowrap;
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
