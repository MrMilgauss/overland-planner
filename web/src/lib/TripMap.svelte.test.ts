// The trip map component (slice 09 step 10-04, 12b step 12-04): with a run it reads the map settings once and the geometry of the run shown,
// hands the built style to MapLibre, and tells a failed answer in the planner's words. MapLibre needs WebGL, which
// jsdom lacks, so the library (a third party, not the planner's port) is replaced here and checked in a real browser by
// tests/e2e/run-map.spec.ts and trip-workflow.spec.ts; the planner's API is a fetch stub. Without a run it draws the
// trip's items (D288).
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11).
import '@testing-library/jest-dom/vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const maps = vi.hoisted(() => ({
  created: [] as {
    style: { layers: { id: string }[] };
    container: HTMLElement;
    center?: number[];
    zoom?: number;
  }[],
  styled: [] as [unknown, { transformStyle: (previous: unknown, next: unknown) => never }][],
  layout: [] as [string, string, string][],
  controls: [] as unknown[],
  markers: [] as { element: HTMLElement; lngLat: unknown }[],
  fitted: [] as unknown[],
  fitOptions: [] as Record<string, unknown>[],
  paint: [] as [string, string, unknown][],
  handlers: {} as Record<string, (event: unknown) => void>,
  images: [] as string[],
  removed: 0,
  workerUrls: [] as string[],
}));

vi.mock('maplibre-gl', () => {
  class FakeMap {
    readonly container: HTMLElement;
    constructor(options: { style: { layers: { id: string }[] }; container: HTMLElement }) {
      this.container = options.container;
      maps.created.push(options);
    }
    on(event: string, handler: (event?: unknown) => void) {
      if (event === 'load' || event === 'style.load') queueMicrotask(handler);
      else maps.handlers[event] = handler;
      return this;
    }
    getCenter() {
      return { lng: 7, lat: 45 };
    }
    getZoom() {
      return 9;
    }
    project([lng, lat]: [number, number]) {
      return { x: lng * 100, y: lat * 100 };
    }
    addControl(control: unknown) {
      maps.controls.push(control);
    }
    addImage(name: string) {
      maps.images.push(name);
    }
    hasImage(name: string) {
      return maps.images.includes(name);
    }
    setStyle(
      style: unknown,
      options: { transformStyle: (previous: unknown, next: unknown) => never },
    ) {
      maps.styled.push([style, options]);
    }
    getLayer(id: string) {
      return { id };
    }
    setLayoutProperty(layer: string, name: string, value: string) {
      maps.layout.push([layer, name, value]);
    }
    fitBounds(bounds: unknown, options: Record<string, unknown> = {}) {
      maps.fitted.push(bounds);
      maps.fitOptions.push(options);
    }
    setPaintProperty(layer: string, name: string, value: unknown) {
      maps.paint.push([layer, name, value]);
    }
    remove() {
      maps.removed += 1;
    }
  }
  class FakeMarker {
    constructor(private readonly options: { element: HTMLElement }) {}
    setLngLat(lngLat: unknown) {
      const known = maps.markers.find((placed) => placed.element === this.options.element);
      if (known) known.lngLat = lngLat;
      else maps.markers.push({ element: this.options.element, lngLat });
      return this;
    }
    addTo(map: { container: HTMLElement }) {
      map.container.appendChild(this.options.element); // on the map's page, where its box can be read
      return this;
    }
  }
  class AttributionControl {
    constructor(public readonly options: unknown) {}
  }
  class NavigationControl {}
  const setWorkerUrl = (url: string): void => void maps.workerUrls.push(url);
  return { setWorkerUrl, Map: FakeMap, Marker: FakeMarker, AttributionControl, NavigationControl };
});

import TripMap from './TripMap.svelte';
import { TerrainChoice } from './terrainChoice';
import { CREDIT_LAYER, stopOpacity, TERRAIN_LAYER } from './runMap';

const CONFIG = {
  tile_url: 'https://tiles.example.test/{z}/{x}/{y}.png',
  attribution: 'Credit',
  max_zoom: 17,
  base_style_url: 'https://styles.example.test/light.json',
  base_attribution: 'Light credit',
};
const GEOMETRY = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: [
          [7, 45],
          [7.1, 45.1],
        ],
      },
      properties: {
        kind: 'track',
        stop: 2,
        item_id: 'i',
        name: 'T',
        level: null,
        reason: null,
        geometry: 'available',
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [7, 45] },
      properties: { marker: 'stop', stop: 2, item_id: 'i', name: 'T', end_stop: null },
    },
  ],
};

let calls: string[];

function planner(routes: Record<string, { status: number; body: unknown }>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url);
      const reply = routes[url] ?? {
        status: 404,
        body: { code: 'not_found', message: 'nothing here' },
      };
      return new Response(JSON.stringify(reply.body), { status: reply.status });
    }),
  );
}

beforeEach(() => {
  calls = [];
  maps.created.length =
    maps.controls.length =
    maps.markers.length =
    maps.fitted.length =
    maps.fitOptions.length =
    maps.paint.length =
    maps.images.length =
      0;
  maps.removed = 0;
  maps.styled.length = maps.layout.length = 0;
  window.localStorage.clear();
  maps.workerUrls.length = 0;
  maps.handlers = {};
});
afterEach(() => vi.unstubAllGlobals());

describe('TripMap with a run', () => {
  it('gives MapLibre its worker as a file of the build, so that the lines are computed in the browser', async () => {
    planner({
      '/api/config/map': { status: 200, body: CONFIG },
      '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
    });
    render(TripMap, { planRunId: 'r1' });
    await waitFor(() => expect(maps.created).toHaveLength(1));
    expect(maps.workerUrls).toHaveLength(1);
    expect(maps.workerUrls[0]).toMatch(/maplibre-gl-worker.*\.mjs/);
  });

  it('draws the run: the style, an arrow image, its markers, a fit to the bounds and a credit that stays open', async () => {
    planner({
      '/api/config/map': { status: 200, body: CONFIG },
      '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
    });
    render(TripMap, { planRunId: 'r1' });
    await waitFor(() => expect(maps.fitted).toHaveLength(1));
    expect(screen.getByRole('region', { name: 'Map of the run' })).toBeInTheDocument();
    expect(maps.created[0].style).toMatchObject({ sources: { tiles: { attribution: 'Credit' } } });
    expect(maps.images).toEqual(['direction-arrow']);
    expect(maps.markers.map((m) => m.element.textContent)).toEqual(['2']);
    expect(maps.controls).toContainEqual(expect.objectContaining({ options: { compact: false } }));
    expect(maps.fitted[0]).toEqual([
      [7, 45],
      [7.1, 45.1],
    ]);
  });

  it('reads the settings once and the geometry again for another run, drawing it afresh', async () => {
    planner({
      '/api/config/map': { status: 200, body: CONFIG },
      '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
      '/api/plan-runs/r2/geometry': { status: 200, body: GEOMETRY },
    });
    const { rerender } = render(TripMap, { planRunId: 'r1' });
    await waitFor(() => expect(maps.fitted).toHaveLength(1));
    await rerender({ planRunId: 'r2' });
    await waitFor(() => expect(maps.fitted).toHaveLength(2));
    expect(calls.filter((url) => url === '/api/config/map')).toHaveLength(1);
    expect(calls).toContain('/api/plan-runs/r2/geometry');
    expect(maps.removed).toBeGreaterThanOrEqual(1);
  });

  it("says so in the planner's words when the geometry cannot be had, and draws no map", async () => {
    planner({
      '/api/config/map': { status: 200, body: CONFIG },
      '/api/plan-runs/r1/geometry': {
        status: 404,
        body: { code: 'run_has_no_route', message: 'This plan run has no route to draw' },
      },
    });
    render(TripMap, { planRunId: 'r1' });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This plan run has no route to draw',
    );
    expect(maps.created).toHaveLength(0);
  });

  describe('the light base map and Terrain (D287)', () => {
    const BASE = {
      version: 8,
      sources: {},
      layers: [
        { id: 'bg', type: 'background' },
        { id: 'labels', type: 'symbol' },
      ],
    };

    async function started(routes: Record<string, { status: number; body: unknown }> = {}) {
      planner({
        '/api/config/map': { status: 200, body: CONFIG },
        '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
        ...routes,
      });
      render(TripMap, { planRunId: 'r1' });
      await waitFor(() => expect(maps.fitted).toHaveLength(1));
    }

    const terrainControl = (): HTMLElement =>
      (maps.controls as { onAdd?: (map: unknown) => HTMLElement }[]).find(
        (control) => control.onAdd,
      )!.onAdd!({});

    it('starts on its own style, then adopts the fetched base map with the run layers last', async () => {
      await started({ [CONFIG.base_style_url]: { status: 200, body: BASE } });
      await waitFor(() => expect(maps.styled).toHaveLength(1));
      expect(maps.created[0].style.layers.map((l) => l.id)[0]).toBe('plain-background');
      const [base, options] = maps.styled[0];
      expect(base).toEqual(BASE);
      const adopted = options.transformStyle(maps.created[0].style, base) as {
        layers: { id: string }[];
      };
      const ids = adopted.layers.map((l) => l.id);
      expect(ids.slice(0, 2)).toEqual(['bg', 'labels']);
      expect(ids.indexOf('track')).toBeGreaterThan(ids.indexOf('labels'));
    });

    it('keeps the route on the plain background when the base map cannot be had', async () => {
      await started(); // the style address answers 404
      await waitFor(() => expect(calls).toContain(CONFIG.base_style_url));
      expect(maps.styled).toHaveLength(0);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('has a Terrain button that shows and hides the Terrain layer, swaps the credit, and is remembered', async () => {
      await started();
      const button = terrainControl().querySelector('button')!;
      expect(button).toHaveTextContent('Terrain');
      expect(button).toHaveAttribute('aria-pressed', 'false');
      await fireEvent.click(button);
      expect(button).toHaveAttribute('aria-pressed', 'true');
      expect(maps.layout).toContainEqual([TERRAIN_LAYER, 'visibility', 'visible']);
      expect(maps.layout).toContainEqual([CREDIT_LAYER, 'visibility', 'none']);
      expect(new TerrainChoice().terrain()).toBe(true);
      await fireEvent.click(button);
      expect(button).toHaveAttribute('aria-pressed', 'false');
      expect(maps.layout).toContainEqual([TERRAIN_LAYER, 'visibility', 'none']);
      expect(new TerrainChoice().terrain()).toBe(false);
    });

    it('opens on Terrain when that was the last choice', async () => {
      new TerrainChoice().choose(true);
      await started();
      expect(maps.created[0].style.layers.find((l) => l.id === TERRAIN_LAYER)).toMatchObject({
        layout: { visibility: 'visible' },
      });
      expect(terrainControl().querySelector('button')).toHaveAttribute('aria-pressed', 'true');
    });
  });

  describe('the estimate chip (D267)', () => {
    const NOTE = 'estimate: road legs are straight-line guesses, not real roads';

    async function drawnWith(props: { estimate?: boolean }) {
      planner({
        '/api/config/map': { status: 200, body: CONFIG },
        '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
      });
      render(TripMap, { planRunId: 'r1', ...props });
      await waitFor(() => expect(maps.fitted).toHaveLength(1));
    }

    it('shows a chip in the map while an estimate run is shown', async () => {
      await drawnWith({ estimate: true });
      const chip = screen.getByRole('note', { name: NOTE });
      expect(chip).toHaveTextContent('Estimate');
      expect(chip).toHaveAttribute('title', NOTE);
      expect(chip.closest('.frame')).not.toBeNull();
    });

    it.each([[{ estimate: false }], [{}]])('shows no chip for %j', async (props) => {
      await drawnWith(props);
      expect(screen.queryByRole('note')).not.toBeInTheDocument();
    });
  });

  describe("before any route: the trip's items (D288)", () => {
    const SUSA = {
      id: 'susa',
      type: 'poi' as const,
      name: 'Susa, piazza',
      included: true,
      anchor: 'start' as const,
      location: { lat: 45.14, lon: 7.05 },
      entry: null,
      exit: null,
      length_m: null,
    };
    const ASSIETTA = {
      id: 'assietta',
      type: 'track' as const,
      name: "Strada dell'Assietta",
      included: true,
      anchor: null,
      location: null,
      entry: { lat: 45.05, lon: 7.04 },
      exit: { lat: 44.95, lon: 6.88 },
      length_m: 34_200,
    };

    function plannerWithoutRun(): void {
      planner({ '/api/config/map': { status: 200, body: CONFIG } });
    }

    it('draws a place as a dot with its tag, a trail by its entry and exit, and fits them, reading no geometry', async () => {
      plannerWithoutRun();
      render(TripMap, { items: [SUSA, ASSIETTA] });
      await waitFor(() => expect(maps.fitted).toHaveLength(1));

      const drawn = maps.markers.map((m) => [
        m.element.className,
        m.element.title,
        m.element.textContent,
      ]);
      expect(drawn).toEqual([
        ['run-marker place', 'Susa, piazza', 'Start'],
        ['run-marker entry', "Entry of Strada dell'Assietta", ''],
        ['run-marker exit', "Exit of Strada dell'Assietta", ''],
      ]);
      expect(maps.fitted[0]).toEqual([
        [6.88, 44.95],
        [7.05, 45.14],
      ]);
      expect(calls.some((url) => url.includes('geometry'))).toBe(false);
    });

    it('opens on a default view of the western Alps when the trip is empty', async () => {
      plannerWithoutRun();
      render(TripMap, { items: [] });
      await waitFor(() => expect(maps.created).toHaveLength(1));

      expect(maps.fitted).toHaveLength(0);
      expect(maps.created[0]).toMatchObject({ center: [6.9, 44.9], zoom: 7 });
    });

    it('draws the new set of items when the trip changes, and the run once there is one', async () => {
      planner({
        '/api/config/map': { status: 200, body: CONFIG },
        '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
      });
      const { rerender } = render(TripMap, { items: [SUSA] });
      await waitFor(() => expect(maps.fitted).toHaveLength(1));
      await rerender({ items: [SUSA, ASSIETTA] });
      await waitFor(() => expect(maps.fitted).toHaveLength(2));
      await rerender({ planRunId: 'r1', items: [SUSA, ASSIETTA] });
      await waitFor(() => expect(maps.fitted).toHaveLength(3));

      expect(maps.markers.at(-1)!.element.textContent).toBe('2'); // the run's stop number
    });

    it('adds a place by a click on the map without a run', async () => {
      planner({
        '/api/config/map': { status: 200, body: CONFIG },
        '/api/projects/p1/pois': { status: 201, body: { id: 'n' } },
      });
      const added = vi.fn();
      render(TripMap, { items: [SUSA], projectId: 'p1', onplaceadded: added });
      await waitFor(() => expect(maps.fitted).toHaveLength(1));

      await fireEvent.click(screen.getByRole('button', { name: 'Click on map to add' }));
      maps.handlers.click({ point: { x: 50, y: 60 }, lngLat: { lng: 7.0486001, lat: 45.1376004 } });
      await fireEvent.input(await screen.findByLabelText('Name'), { target: { value: 'Lago' } });
      await fireEvent.click(screen.getByRole('button', { name: 'Add' }));

      await waitFor(() => expect(added).toHaveBeenCalledTimes(1));
    });
  });

  describe('the Terrain button when pressed (12-02 defect)', () => {
    // bypass: jsdom does not run MapLibre's own stylesheet, so the cascade is checked in a browser by
    // trip-workflow.spec.ts; here only the rule that must outrank MapLibre's hover look is held to its selector.
    it("has a pressed rule that outranks the control group's hover rule", () => {
      const source = readFileSync(path.join(__dirname, 'TripMap.svelte'), 'utf8');
      expect(source).toMatch(/button\.terrain-button\[aria-pressed='true'\]:not\(:disabled\)/);
    });
  });

  describe('the "Click on map" mode (step 10-05)', () => {
    const click = (x: number, y: number, lng: number, lat: number) =>
      maps.handlers.click({ point: { x, y }, lngLat: { lng, lat } });

    async function drawn() {
      const added = vi.fn();
      const view = render(TripMap, { planRunId: 'r1', projectId: 'p1', onplaceadded: added });
      await waitFor(() => expect(maps.fitted).toHaveLength(1));
      return { added, view };
    }

    function acceptingPlaces() {
      planner({
        '/api/config/map': { status: 200, body: CONFIG },
        '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
        '/api/projects/p1/pois': { status: 201, body: { id: 'n' } },
      });
    }

    it('opens a name form at a click and adds the place at the clicked coordinates', async () => {
      acceptingPlaces();
      const { added } = await drawn();
      click(50, 60, 7.0486001, 45.1376004); // not in the mode: no form
      expect(screen.queryByRole('form', { name: 'Add a place here' })).not.toBeInTheDocument();
      await fireEvent.click(screen.getByRole('button', { name: 'Click on map to add' }));
      expect(screen.getByRole('button', { name: 'Click on map to add' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      click(50, 60, 7.0486001, 45.1376004);
      await fireEvent.input(await screen.findByLabelText('Name'), {
        target: { value: 'Susa trailhead' },
      });
      await fireEvent.click(screen.getByRole('button', { name: 'Add' }));
      await waitFor(() => expect(added).toHaveBeenCalledTimes(1));
      const post = vi.mocked(fetch).mock.calls.find(([url]) => url === '/api/projects/p1/pois')!;
      expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({
        name: 'Susa trailhead',
        lat: 45.1376,
        lon: 7.0486,
      });
      expect(screen.queryByRole('form', { name: 'Add a place here' })).not.toBeInTheDocument();
    });

    it('closes the form on a click elsewhere and adds nothing', async () => {
      acceptingPlaces();
      await drawn();
      await fireEvent.click(screen.getByRole('button', { name: 'Click on map to add' }));
      click(703, 4505, 7.03, 45.05);
      expect(await screen.findByRole('form', { name: 'Add a place here' })).toBeInTheDocument();
      click(10, 10, 6.5, 44.5);
      await waitFor(() =>
        expect(screen.queryByRole('form', { name: 'Add a place here' })).not.toBeInTheDocument(),
      );
      expect(vi.mocked(fetch).mock.calls.some(([url]) => url === '/api/projects/p1/pois')).toBe(
        false,
      );
    });
  });

  describe('the retrace label after each move (D270)', () => {
    // A retrace of one degree, so that the fake map's pixels (100 a degree) put its middle at (750, 4550), a quarter at
    // (725, 4525) and three quarters at (775, 4575); the label is 40 x 16 px, the stop number a box set by the test.
    const RETRACE = {
      type: 'FeatureCollection',
      features: [
        {
          ...GEOMETRY.features[0],
          geometry: {
            type: 'LineString',
            coordinates: [
              [7, 45],
              [8, 46],
            ],
          },
          properties: { ...GEOMETRY.features[0].properties, kind: 'retrace' },
        },
        GEOMETRY.features[1],
      ],
    };
    let stopNumber: { left: number; top: number; right: number; bottom: number };
    const box = (l: number, t: number, r: number, b: number) => ({
      left: l,
      top: t,
      right: r,
      bottom: b,
      x: l,
      y: t,
      width: r - l,
      height: b - t,
      toJSON: () => ({}),
    });

    beforeEach(() => {
      stopNumber = { left: 0, top: 0, right: 1, bottom: 1 };
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
        this: HTMLElement,
      ) {
        if (this.classList.contains('numbered')) {
          return box(stopNumber.left, stopNumber.top, stopNumber.right, stopNumber.bottom);
        }
        if (this.classList.contains('retrace')) return box(0, 0, 40, 16);
        return box(0, 0, 0, 0);
      });
    });
    afterEach(() => vi.restoreAllMocks());

    async function drawnRetrace(): Promise<{ label: HTMLElement; at: () => unknown }> {
      planner({
        '/api/config/map': { status: 200, body: CONFIG },
        '/api/plan-runs/r1/geometry': { status: 200, body: RETRACE },
      });
      render(TripMap, { planRunId: 'r1' });
      await waitFor(() => expect(maps.fitted).toHaveLength(1));
      const placed = maps.markers.find((m) => m.element.classList.contains('retrace'))!;
      return { label: placed.element, at: () => placed.lngLat };
    }
    const move = (): void => maps.handlers['moveend']({});

    it('keeps the label at the middle when no stop number is under it', async () => {
      const { label, at } = await drawnRetrace();
      move();
      expect(label.style.display).not.toBe('none');
      expect(at()).toEqual([7.5, 45.5]);
    });

    it('moves it to a quarter when a stop number covers the middle, and hides it when all are covered', async () => {
      const { label, at } = await drawnRetrace();
      stopNumber = { left: 740, top: 4540, right: 760, bottom: 4560 };
      move();
      expect(label.style.display).not.toBe('none');
      expect(at()).toEqual([7.25, 45.25]);
      stopNumber = { left: 600, top: 4400, right: 900, bottom: 4700 };
      move();
      expect(label.style.display).toBe('none');
    });

    it('brings a hidden label back, at the middle, when a move leaves the stop numbers clear of it', async () => {
      const { label, at } = await drawnRetrace();
      stopNumber = { left: 600, top: 4400, right: 900, bottom: 4700 };
      move();
      expect(label.style.display).toBe('none');
      stopNumber = { left: 0, top: 0, right: 1, bottom: 1 };
      move();
      expect(label.style.display).not.toBe('none');
      expect(at()).toEqual([7.5, 45.5]);
    });
  });
});

describe('TripMap with a stop selected (D286)', () => {
  const marker = (stop: number, at: [number, number]) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: at },
    properties: { marker: 'stop', stop, item_id: 'i', name: `S${stop}`, end_stop: null },
  });
  const road = (stop: number, from: [number, number], to: [number, number]) => ({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [from, to] },
    properties: {
      kind: 'road',
      stop,
      item_id: 'i',
      name: `S${stop}`,
      level: 'confirmed',
      reason: null,
      geometry: 'available',
    },
  });
  const TWO_STOPS = {
    type: 'FeatureCollection',
    features: [
      road(2, [7, 45], [7.05, 45.05]),
      road(3, [7.05, 45.05], [7.1, 45.1]),
      marker(2, [7.05, 45.05]),
      marker(3, [7.1, 45.1]),
    ],
  };

  // The page's own way of changing the selection: one reactive prop of its own, so that nothing else is touched (the
  // testing library's rerender replaces every prop at once).
  const mounted: ReturnType<typeof mount>[] = [];
  afterEach(() => mounted.splice(0).forEach((component) => unmount(component)));

  async function drawn(onselectstop = vi.fn()) {
    planner({
      '/api/config/map': { status: 200, body: CONFIG },
      '/api/plan-runs/r1/geometry': { status: 200, body: TWO_STOPS },
    });
    const props = $state({
      planRunId: 'r1',
      selectedStop: undefined as number | undefined,
      onselectstop,
    });
    mounted.push(mount(TripMap, { target: document.body, props }));
    flushSync();
    await waitFor(() => expect(maps.fitted).toHaveLength(1));
    const control = (maps.controls as { onAdd?: (map: unknown) => HTMLElement }[]).filter(
      (candidate) => candidate.onAdd,
    )[1].onAdd!({});
    const numbered = (text: string) =>
      maps.markers.find((placed) => placed.element.textContent === text)!.element;
    const view = {
      rerender: async (next: { selectedStop: number | undefined }) => {
        props.selectedStop = next.selectedStop;
        flushSync();
      },
    };
    return { view, control, numbered, onselectstop };
  }

  it('fits the stop (padding 48, zoom 13 at most), rings its number, dims the other lines and offers Show whole route', async () => {
    const { view, control, numbered } = await drawn();
    expect(control.hidden).toBe(true);
    expect(maps.paint).toEqual([]);

    await view.rerender({ selectedStop: 3 });

    await waitFor(() => expect(maps.fitted).toHaveLength(2));
    expect(maps.fitted[1]).toEqual([
      [7.05, 45.05],
      [7.1, 45.1],
    ]);
    expect(maps.fitOptions[1]).toMatchObject({ padding: 48, maxZoom: 13, animate: false });
    expect(numbered('3')).toHaveClass('selected');
    expect(numbered('2')).not.toHaveClass('selected');
    expect(maps.paint).toContainEqual(['road-confirmed', 'line-opacity', stopOpacity(3)]);
    expect(maps.paint).toContainEqual(['track-arrows', 'icon-opacity', stopOpacity(3)]);
    expect(maps.created[0].container.dataset.selectedStop).toBe('3');
    expect(control.hidden).toBe(false);
  });

  it('fits the whole route again and draws every line in full once the selection is cleared', async () => {
    const { view, control, numbered } = await drawn();
    await view.rerender({ selectedStop: 3 });
    await waitFor(() => expect(maps.fitted).toHaveLength(2));

    await view.rerender({ selectedStop: undefined });

    await waitFor(() => expect(maps.fitted).toHaveLength(3));
    expect(maps.fitted[2]).toEqual([
      [7, 45],
      [7.1, 45.1],
    ]);
    expect(maps.fitOptions[2]).toMatchObject({ padding: 48 });
    expect(maps.fitOptions[2]).not.toHaveProperty('maxZoom');
    expect(maps.paint.at(-1)).toEqual(['track-arrows', 'icon-opacity', 1]);
    expect(numbered('3')).not.toHaveClass('selected');
    expect(maps.created[0].container.dataset.selectedStop).toBe('');
    expect(control.hidden).toBe(true);
  });

  it('tells the page the stop of a number marker pressed, and clears with the Show whole route control', async () => {
    const { control, numbered, onselectstop } = await drawn();

    await fireEvent.click(numbered('2'));
    expect(onselectstop).toHaveBeenLastCalledWith(2);

    await fireEvent.click(control.querySelector('button')!);
    expect(onselectstop).toHaveBeenLastCalledWith(undefined);
    expect(control.querySelector('button')).toHaveTextContent('Show whole route');
  });
});
