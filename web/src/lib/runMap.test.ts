// The run map's sources, layers and overlays, built from the geometry answer and the map settings (slice 09, step
// 10-04, ADR-003 Amendment 2). jsdom has no WebGL, so the drawing is checked here as data and in a real browser by
// tests/e2e/run-map.spec.ts.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11); the rules are pinned by
// examples, one per style of the map; the geometry's own rules are property-tested on the server (step 10-02).
import { describe, expect, it } from 'vitest';
import {
  ARROW_IMAGE,
  arrowImage,
  buildRunMap,
  type LineFeature,
  type LineProperties,
  type MapConfig,
  type MarkerFeature,
  type MarkerProperties,
  type RunGeometry,
  type RunMapPlan,
  placeClicked,
  SNAP_PIXELS,
} from './runMap';

const CONFIG: MapConfig = {
  tile_url: 'https://tiles.example.test/{z}/{x}/{y}.png',
  attribution: 'Map data: OpenStreetMap contributors | Map style: OpenTopoMap',
  max_zoom: 17,
};

function line(
  coordinates: [number, number][],
  properties: Partial<LineProperties> = {},
): LineFeature {
  return {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates },
    properties: {
      kind: 'road',
      stop: 2,
      item_id: 'i1',
      name: 'Briancon',
      level: 'confirmed',
      reason: null,
      geometry: 'available',
      ...properties,
    },
  };
}

function marker(point: [number, number], properties: Partial<MarkerProperties>): MarkerFeature {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: point },
    properties: {
      marker: 'stop',
      stop: 1,
      item_id: 'i1',
      name: 'Casa',
      end_stop: null,
      ...properties,
    },
  };
}

function collection(...features: (LineFeature | MarkerFeature)[]): RunGeometry {
  return { type: 'FeatureCollection', features };
}

function layer(plan: RunMapPlan, id: string) {
  return plan.style.layers.find((candidate) => candidate.id === id);
}

function drawnLines(plan: RunMapPlan): LineFeature[] {
  const source = plan.style.sources['run'];
  if (source?.type !== 'geojson' || typeof source.data === 'string') throw new Error('no lines');
  return (source.data as unknown as RunGeometry).features as LineFeature[];
}

const ROAD: [number, number][] = [
  [7.0, 45.0],
  [7.0, 45.2],
  [7.0, 45.4],
];

describe('the base map', () => {
  it('draws the chosen tiles first and carries their credit and top zoom', () => {
    const plan = buildRunMap(collection(line(ROAD)), CONFIG);
    expect(plan.style.sources['tiles']).toMatchObject({
      type: 'raster',
      tiles: [CONFIG.tile_url],
      tileSize: 256,
      maxzoom: 17,
      attribution: CONFIG.attribution,
    });
    expect(plan.style.layers[0]).toMatchObject({ id: 'tiles', type: 'raster', source: 'tiles' });
  });

  it('puts only the lines in the run source, markers being overlays', () => {
    const plan = buildRunMap(
      collection(line(ROAD), marker([7, 45], { marker: 'stop', stop: 1 })),
      CONFIG,
    );
    expect(drawnLines(plan)).toHaveLength(1);
  });

  it('fits every feature in its bounds, and has none for an empty run', () => {
    const plan = buildRunMap(
      collection(line(ROAD), marker([8.5, 44.0], { marker: 'start', stop: 1 })),
      CONFIG,
    );
    expect(plan.bounds).toEqual([
      [7.0, 44.0],
      [8.5, 45.4],
    ]);
    expect(buildRunMap(collection(), CONFIG).bounds).toBeNull();
  });
});

describe('line styles (ADR-003 Amendment 2)', () => {
  const plan = buildRunMap(
    collection(
      line(ROAD, { kind: 'road', level: 'confirmed' }),
      line(ROAD, { kind: 'road', level: 'unconfirmed', reason: 'No road open at night' }),
      line(ROAD, { kind: 'road', level: 'confirmed', geometry: 'unavailable' }),
      line(ROAD, { kind: 'retrace', level: 'unconfirmed' }),
      line(ROAD, { kind: 'track', level: null }),
    ),
    CONFIG,
  );

  it.each([
    ['road-confirmed', { 'line-color': '#1d4ed8' }, 'line-dasharray'],
    ['road-unconfirmed', { 'line-color': '#ea580c', 'line-dasharray': [0.5, 2] }, undefined],
    ['retrace', { 'line-color': '#7e22ce', 'line-dasharray': [8, 4] }, undefined],
    ['track', { 'line-color': '#14532d' }, 'line-dasharray'],
    ['unavailable', { 'line-color': '#6b7280', 'line-dasharray': [2, 2] }, undefined],
  ])('draws %s in its own colour and dashes', (id, paint, absent) => {
    const drawn = layer(plan, id);
    expect(drawn).toMatchObject({ type: 'line', source: 'run', paint });
    if (absent) expect((drawn as { paint: object }).paint).not.toHaveProperty(absent);
  });

  it('keeps an unavailable leg out of the Confirmed and Unconfirmed layers', () => {
    expect(JSON.stringify(layer(plan, 'road-confirmed'))).toContain('"available"');
    expect(JSON.stringify(layer(plan, 'road-unconfirmed'))).toContain('"available"');
    expect(JSON.stringify(layer(plan, 'unavailable'))).toContain('"unavailable"');
  });

  it('puts direction arrows along tracks only, an image drawn at load', () => {
    const arrows = layer(plan, 'track-arrows');
    expect(arrows).toMatchObject({
      type: 'symbol',
      source: 'run',
      layout: { 'symbol-placement': 'line', 'icon-image': ARROW_IMAGE },
    });
    expect(JSON.stringify((arrows as { filter: unknown }).filter)).toContain('track');
    expect(JSON.stringify((arrows as { filter: unknown }).filter)).not.toContain('retrace');
    expect(plan.style.layers.filter((l) => l.type === 'symbol').map((l) => l.id)).toEqual([
      'track-arrows',
    ]);
  });
});

describe('labels at the middle of a line', () => {
  const uneven: [number, number][] = [
    [7.0, 45.0],
    [7.0, 45.1],
    [7.0, 45.4],
  ];

  it('puts "!" at the middle of an Unconfirmed leg, with its reason', () => {
    const plan = buildRunMap(
      collection(line(uneven, { level: 'unconfirmed', reason: 'No road open at night' })),
      CONFIG,
    );
    expect(plan.overlays).toEqual([
      { kind: 'unconfirmed', text: '!', title: 'No road open at night', lngLat: [7.0, 45.2] },
    ]);
  });

  it('labels a retrace "retrace" at its middle, with no arrow', () => {
    const plan = buildRunMap(
      collection(line(ROAD, { kind: 'retrace', stop: 6, level: 'unconfirmed' })),
      CONFIG,
    );
    expect(plan.overlays).toMatchObject([
      { kind: 'retrace', text: 'retrace', lngLat: [7.0, 45.2] },
    ]);
  });

  it('labels an unavailable road leg "geometry unavailable", whatever its level', () => {
    const plan = buildRunMap(
      collection(line(ROAD, { level: 'unconfirmed', geometry: 'unavailable' })),
      CONFIG,
    );
    expect(plan.overlays).toMatchObject([{ kind: 'unavailable', text: 'geometry unavailable' }]);
  });

  it('labels an unavailable track like any unavailable line, and keeps arrows off it', () => {
    const plan = buildRunMap(
      collection(line(ROAD, { kind: 'track', level: null, geometry: 'unavailable' })),
      CONFIG,
    );
    expect(plan.overlays).toMatchObject([{ kind: 'unavailable', text: 'geometry unavailable' }]);
    expect(JSON.stringify((layer(plan, 'track-arrows') as { filter: unknown }).filter)).toContain(
      '"available"',
    );
  });

  it('draws the map whole when a line has no point or one point', () => {
    const plan = buildRunMap(
      collection(
        line([], { geometry: 'unavailable' }),
        line([[7.0, 45.0]], { geometry: 'unavailable' }),
      ),
      CONFIG,
    );
    expect(plan.overlays).toMatchObject([{ kind: 'unavailable', lngLat: [7.0, 45.0] }]);
  });

  it('labels nothing on a Confirmed road or a track', () => {
    const plan = buildRunMap(
      collection(line(ROAD), line(ROAD, { kind: 'track', level: null })),
      CONFIG,
    );
    expect(plan.overlays).toEqual([]);
  });
});

describe('markers', () => {
  it('numbers stops, and the one S/E marker of a round trip with both its numbers', () => {
    const plan = buildRunMap(
      collection(
        marker([7.0, 45.0], { marker: 'start_end', stop: 1, end_stop: 11, name: 'Casa' }),
        marker([7.1, 45.1], { marker: 'stop', stop: 2, name: 'Assietta' }),
        marker([7.1, 45.1], { marker: 'entry', stop: 2, name: 'Assietta' }),
        marker([7.2, 45.2], { marker: 'exit', stop: 2, name: 'Assietta' }),
        marker([7.3, 45.3], { marker: 'start', stop: 1, name: 'A' }),
        marker([7.4, 45.4], { marker: 'end', stop: 5, name: 'B' }),
      ),
      CONFIG,
    );
    expect(plan.overlays).toEqual([
      { kind: 'start_end', text: 'S/E 1 and 11', title: '1 and 11. Casa', lngLat: [7.0, 45.0] },
      { kind: 'stop', text: '2', title: '2. Assietta', lngLat: [7.1, 45.1] },
      { kind: 'entry', text: '', title: 'Entry of Assietta', lngLat: [7.1, 45.1] },
      { kind: 'exit', text: '', title: 'Exit of Assietta', lngLat: [7.2, 45.2] },
      { kind: 'start', text: 'S 1', title: '1. A', lngLat: [7.3, 45.3] },
      { kind: 'end', text: 'E 5', title: '5. B', lngLat: [7.4, 45.4] },
    ]);
  });
});

describe('the direction arrow image', () => {
  it('points right: solid at its tip, clear at the far corners and behind', () => {
    const { width, height, data } = arrowImage();
    const alpha = (x: number, y: number): number => data[(y * width + x) * 4 + 3];
    expect([width, height]).toEqual([24, 24]);
    expect(alpha(12, 12)).toBe(255);
    expect(alpha(18, 12)).toBe(255);
    expect([alpha(0, 0), alpha(23, 0), alpha(0, 23), alpha(23, 23), alpha(1, 12)]).toEqual([
      0, 0, 0, 0, 0,
    ]);
  });
});

describe('placeClicked: the place a click on the map stands for', () => {
  const ENTRY = { x: 200, y: 100, lngLat: [7.041234567, 45.056] as [number, number] };
  const click = (away: number) => ({ x: ENTRY.x + away, y: ENTRY.y });

  it.each([
    [0, true],
    [11, true],
    [SNAP_PIXELS, true],
    [13, false],
    [60, false],
  ])('a click %i px from an entry or exit marker takes its exact place: %s', (away, snapped) => {
    const place = placeClicked(click(away), [7.0123456789, 45.2], [ENTRY]);
    expect(place).toEqual(
      snapped ? { lat: 45.056, lon: 7.041234567 } : { lat: 45.2, lon: 7.012346 },
    );
  });

  it('takes the nearer of two markers within reach, and rounds a click to 6 decimals', () => {
    const near = { x: 205, y: 100, lngLat: [7.5, 45.5] as [number, number] };
    expect(placeClicked({ x: 204, y: 100 }, [1, 2], [ENTRY, near])).toEqual({
      lat: 45.5,
      lon: 7.5,
    });
    expect(placeClicked({ x: 0, y: 0 }, [7.12345649, 45.1234565], [])).toEqual({
      lat: 45.123457,
      lon: 7.123456,
    });
  });
});
