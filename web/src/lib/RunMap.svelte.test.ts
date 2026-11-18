// The run map component (slice 09, step 10-04): it reads the map settings once and the geometry of the run shown,
// hands the built style to MapLibre, and tells a failed answer in the planner's words. MapLibre needs WebGL, which
// jsdom lacks, so the library (a third party, not the planner's port) is replaced here and checked in a real browser by
// tests/e2e/run-map.spec.ts; the planner's API is a fetch stub.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11).
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const maps = vi.hoisted(() => ({
  created: [] as { style: unknown; container: HTMLElement }[],
  controls: [] as unknown[],
  markers: [] as { element: HTMLElement; lngLat: unknown }[],
  fitted: [] as unknown[],
  handlers: {} as Record<string, (event: unknown) => void>,
  images: [] as string[],
  removed: 0,
  workerUrls: [] as string[],
}));

vi.mock('maplibre-gl', () => {
  class FakeMap {
    constructor(options: { style: unknown; container: HTMLElement }) {
      maps.created.push(options);
    }
    on(event: string, handler: (event?: unknown) => void) {
      if (event === 'load') queueMicrotask(handler);
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
    fitBounds(bounds: unknown) {
      maps.fitted.push(bounds);
    }
    remove() {
      maps.removed += 1;
    }
  }
  class FakeMarker {
    constructor(private readonly options: { element: HTMLElement }) {}
    setLngLat(lngLat: unknown) {
      maps.markers.push({ element: this.options.element, lngLat });
      return this;
    }
    addTo() {
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

import RunMap from './RunMap.svelte';

const CONFIG = {
  tile_url: 'https://tiles.example.test/{z}/{x}/{y}.png',
  attribution: 'Credit',
  max_zoom: 17,
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
    maps.images.length =
      0;
  maps.removed = 0;
  maps.workerUrls.length = 0;
  maps.handlers = {};
});
afterEach(() => vi.unstubAllGlobals());

describe('RunMap', () => {
  it('gives MapLibre its worker as a file of the build, so that the lines are computed in the browser', async () => {
    planner({
      '/api/config/map': { status: 200, body: CONFIG },
      '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
    });
    render(RunMap, { planRunId: 'r1' });
    await waitFor(() => expect(maps.created).toHaveLength(1));
    expect(maps.workerUrls).toHaveLength(1);
    expect(maps.workerUrls[0]).toMatch(/maplibre-gl-worker.*\.mjs/);
  });

  it('draws the run: the style, an arrow image, its markers, a fit to the bounds and a credit that stays open', async () => {
    planner({
      '/api/config/map': { status: 200, body: CONFIG },
      '/api/plan-runs/r1/geometry': { status: 200, body: GEOMETRY },
    });
    render(RunMap, { planRunId: 'r1' });
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
    const { rerender } = render(RunMap, { planRunId: 'r1' });
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
    render(RunMap, { planRunId: 'r1' });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This plan run has no route to draw',
    );
    expect(maps.created).toHaveLength(0);
  });

  describe('the "Click on map" mode (step 10-05)', () => {
    const click = (x: number, y: number, lng: number, lat: number) =>
      maps.handlers.click({ point: { x, y }, lngLat: { lng, lat } });

    async function drawn() {
      const added = vi.fn();
      const view = render(RunMap, { planRunId: 'r1', projectId: 'p1', onplaceadded: added });
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
      await fireEvent.click(screen.getByRole('button', { name: 'Click on map' }));
      expect(screen.getByRole('button', { name: 'Click on map' })).toHaveAttribute(
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
      await fireEvent.click(screen.getByRole('button', { name: 'Click on map' }));
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
});
