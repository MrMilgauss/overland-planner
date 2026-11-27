// The run map's sources, layers and overlays, built from the geometry answer and the map settings (slice 09, step
// 10-04, ADR-003 Amendment 2). jsdom has no WebGL, so the drawing is checked here as data and in a real browser by
// tests/e2e/run-map.spec.ts.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11); the rules are pinned by
// examples, one per style of the map; the geometry's own rules are property-tested on the server (step 10-02).
import { expression, latest } from '@maplibre/maplibre-gl-style-spec';
import type { StyleSpecification } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';
import type { Item } from './api';
import {
  ARROW_IMAGE,
  adoptBaseStyle,
  arrowImage,
  buildRunMap,
  buildTripMap,
  CREDIT_LAYER,
  DIMMED_OPACITY,
  DIMMED_PAINTS,
  ROAD_COLOUR,
  stopBounds,
  stopOpacity,
  TERRAIN_LAYER,
  TRACK_COLOUR,
  type LineFeature,
  type LineProperties,
  type MapConfig,
  type MarkerFeature,
  type MarkerProperties,
  type RunGeometry,
  type RunMapPlan,
  placeClicked,
  placeRetraceLabel,
  RETRACE_FRACTIONS,
  type ScreenBox,
  SNAP_PIXELS,
} from './runMap';

const CONFIG: MapConfig = {
  tile_url: 'https://tiles.example.test/{z}/{x}/{y}.png',
  attribution: 'Map data: OpenStreetMap contributors | Map style: OpenTopoMap',
  max_zoom: 17,
  base_style_url: 'https://styles.example.test/light.json',
  base_attribution: 'Light credit',
  place_search: true,
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

describe('the map on its own style', () => {
  it('starts on a plain background, then the Terrain tiles hidden, then the route, so that it is never blank', () => {
    const plan = buildRunMap(collection(line(ROAD)), CONFIG);
    expect(plan.style.sources['tiles']).toMatchObject({
      type: 'raster',
      tiles: [CONFIG.tile_url],
      tileSize: 256,
      maxzoom: 17,
      attribution: CONFIG.attribution,
    });
    const ids = plan.style.layers.map((l) => l.id);
    expect(ids.slice(0, 3)).toEqual(['plain-background', CREDIT_LAYER, TERRAIN_LAYER]);
    expect(ids.indexOf('track')).toBeGreaterThan(ids.indexOf(TERRAIN_LAYER));
    expect(layer(plan, TERRAIN_LAYER)).toMatchObject({
      type: 'raster',
      source: 'tiles',
      maxzoom: 18,
      layout: { visibility: 'none' },
    });
    expect(layer(plan, 'plain-background')).toMatchObject({ type: 'background' });
  });

  it('shows the Terrain layer from the start when Terrain is the choice, and then no light credit', () => {
    const plan = buildRunMap(collection(line(ROAD)), CONFIG, true);
    expect(layer(plan, TERRAIN_LAYER)).toMatchObject({ layout: { visibility: 'visible' } });
    expect(layer(plan, CREDIT_LAYER)).toMatchObject({ layout: { visibility: 'none' } });
  });

  it('carries the light base map credit on a source of its own, shown only on the light base map', () => {
    const plan = buildRunMap(collection(line(ROAD)), CONFIG);
    expect(plan.style.sources['base-credit']).toMatchObject({ attribution: 'Light credit' });
    expect(layer(plan, CREDIT_LAYER)).toMatchObject({ source: 'base-credit' });
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

const BASES: [string, StyleSpecification][] = [
  ['no layers', { version: 8, sources: {}, layers: [] }],
  ['one background', { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background' }] }],
  [
    'a background and symbol labels',
    {
      version: 8,
      glyphs: 'https://fonts.example.test/{fontstack}/{range}.pbf',
      sprite: 'https://sprites.example.test/light',
      sources: {
        osm: { type: 'vector', url: 'https://tiles.example.test/osm', attribution: 'Their credit' },
      },
      layers: [
        { id: 'bg', type: 'background' },
        { id: 'labels', type: 'symbol', source: 'osm', 'source-layer': 'place' },
      ],
    },
  ],
];

describe('adopting the light base map (D287)', () => {
  const own = buildRunMap(
    collection(line(ROAD), line(ROAD, { kind: 'track', level: null })),
    CONFIG,
  ).style;
  const routeIds = own.layers.map((l) => l.id).filter((id) => !['plain-background'].includes(id));

  it.each(BASES)(
    'puts the run layers after every base layer, in their own order, for %s',
    (_name, base) => {
      const adopted = adoptBaseStyle(own, base, false);
      expect(adopted.layers.map((l) => l.id)).toEqual([
        ...base.layers.map((l) => l.id),
        ...routeIds,
      ]);
      expect(adopted.sources['run']).toBe(own.sources['run']);
      expect(adopted.sources['tiles']).toBe(own.sources['tiles']);
    },
  );

  it.each(BASES)(
    'keeps the base map glyphs and sprite for %s, and drops the plain background',
    (_n, base) => {
      const adopted = adoptBaseStyle(own, base, false);
      expect(adopted.glyphs).toBe(base.glyphs);
      expect(adopted.sprite).toBe(base.sprite);
      expect(adopted.layers.map((l) => l.id)).not.toContain('plain-background');
    },
  );

  it("credits the light base map once, with the planner's words alone: its own sources say an empty credit", () => {
    const [, base] = BASES[2];
    const adopted = adoptBaseStyle(own, base, false);
    // Empty, not absent: a source given by a TileJSON address would otherwise show the credit that file carries, beside
    // the planner's own (the defect of 12-02: OpenFreeMap named twice).
    expect(adopted.sources['osm']).toMatchObject({ attribution: '' });
    expect(adopted.layers.find((l) => l.id === CREDIT_LAYER)).toMatchObject({
      layout: { visibility: 'visible' },
    });
  });

  it('leaves the light credit hidden when Terrain is on', () => {
    const adopted = adoptBaseStyle(own, BASES[1][1], true);
    expect(adopted.layers.find((l) => l.id === CREDIT_LAYER)).toMatchObject({
      layout: { visibility: 'none' },
    });
  });
});

describe('outlined lines (D287)', () => {
  const plan = buildRunMap(collection(line(ROAD)), CONFIG);
  const ids = plan.style.layers.map((l) => l.id);
  const LINES = ['unavailable', 'road-confirmed', 'road-unconfirmed', 'retrace', 'track'];
  const paintOf = (id: string) => (layer(plan, id) as { paint: Record<string, unknown> }).paint;
  const widthAt = (id: string, zoom: number): number => {
    const made = expression.createExpression(
      paintOf(id)['line-width'] as never,
      latest.paint_line['line-width'] as never,
    );
    if (made.result !== 'success') throw new Error(`${id} line-width is not an expression`);
    return made.value.evaluate({ zoom } as never) as number;
  };

  it.each(LINES)('%s has a white casing with round joins directly below it', (id) => {
    expect(ids[ids.indexOf(id) - 1]).toBe(`${id}-casing`);
    expect(layer(plan, `${id}-casing`)).toMatchObject({
      type: 'line',
      source: 'run',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': '#ffffff' },
    });
    expect(JSON.stringify((layer(plan, `${id}-casing`) as { filter: unknown }).filter)).toBe(
      JSON.stringify((layer(plan, id) as { filter: unknown }).filter),
    );
  });

  it.each(LINES)('%s is 4 px at zoom 8 to 7 px at zoom 13 and its casing 3 px wider', (id) => {
    expect([8, 13, 10.5].map((zoom) => widthAt(id, zoom))).toEqual([4, 7, 5.5]);
    for (const zoom of [8, 10, 13])
      expect(widthAt(`${id}-casing`, zoom) - widthAt(id, zoom)).toBeCloseTo(3);
  });

  it('keeps the colours: road blue, unconfirmed orange, track green, retrace purple, unavailable grey', () => {
    expect(LINES.map((id) => paintOf(id)['line-color'])).toEqual([
      '#6b7280',
      '#1d4ed8',
      '#ea580c',
      '#7e22ce',
      '#14532d',
    ]);
  });

  // WCAG 2.x contrast of a line colour against its white casing (the colour the eye compares it to).
  const luminance = (hex: string): number => {
    const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
    const [r, g, b] = channels.map((c) =>
      c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
    );
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrastWithWhite = (hex: string): number => 1.05 / (luminance(hex) + 0.05);

  it.each(LINES)('%s stands out from white at 3:1 or more', (id) => {
    expect(contrastWithWhite(paintOf(id)['line-color'] as string)).toBeGreaterThanOrEqual(3);
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
      {
        kind: 'start_end',
        text: 'S/E 1 and 11',
        title: '1 and 11. Casa',
        lngLat: [7.0, 45.0],
        stops: [1, 11],
      },
      { kind: 'stop', text: '2', title: '2. Assietta', lngLat: [7.1, 45.1], stops: [2] },
      { kind: 'entry', text: '', title: 'Entry of Assietta', lngLat: [7.1, 45.1] },
      { kind: 'exit', text: '', title: 'Exit of Assietta', lngLat: [7.2, 45.2] },
      { kind: 'start', text: 'S 1', title: '1. A', lngLat: [7.3, 45.3], stops: [1] },
      { kind: 'end', text: 'E 5', title: '5. B', lngLat: [7.4, 45.4], stops: [5] },
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

// A layout setting of the arrow layer as MapLibre evaluates it at a zoom (the expression's shape is not asserted).
function arrowSetting(
  plan: RunMapPlan,
  name: 'icon-size' | 'symbol-spacing',
  zoom: number,
): number {
  const layout = (layer(plan, 'track-arrows') as { layout: Record<string, unknown> }).layout;
  const made = expression.createPropertyExpression(
    layout[name],
    name,
    latest.layout_symbol[name] as never,
  );
  if (made.result !== 'success') throw new Error(`${name} does not evaluate`);
  return made.value.evaluate({ zoom } as never) as number;
}

describe('arrows sized by zoom', () => {
  const plan = buildRunMap(collection(line(ROAD, { kind: 'track', level: null })), CONFIG);
  const TRIP_WIDE = 8;
  const TRAIL = 14;

  it('draws a smaller arrow, and spaces arrows wider, at a trip-wide zoom than at a trail zoom', () => {
    expect(arrowSetting(plan, 'icon-size', TRIP_WIDE)).toBeLessThan(
      arrowSetting(plan, 'icon-size', TRAIL),
    );
    expect(arrowSetting(plan, 'symbol-spacing', TRIP_WIDE)).toBeGreaterThan(
      arrowSetting(plan, 'symbol-spacing', TRAIL),
    );
  });

  it('keeps the arrow within half to full size, and spaced between 80 and 160 px, at any zoom', () => {
    for (const zoom of [0, 4, 8, 11, 13, 17]) {
      expect(arrowSetting(plan, 'icon-size', zoom)).toBeGreaterThanOrEqual(0.5);
      expect(arrowSetting(plan, 'icon-size', zoom)).toBeLessThanOrEqual(1);
      expect(arrowSetting(plan, 'symbol-spacing', zoom)).toBeGreaterThanOrEqual(80);
      expect(arrowSetting(plan, 'symbol-spacing', zoom)).toBeLessThanOrEqual(160);
    }
  });
});

describe('the retrace label keeps clear of stop numbers', () => {
  const LABEL = { width: 40, height: 16 };
  // A label standing at a fraction of a 1000 px line: its box is centred on that spot of the line.
  const labelAt = (fraction: number): ScreenBox => ({
    left: fraction * 1000 - LABEL.width / 2,
    right: fraction * 1000 + LABEL.width / 2,
    top: -LABEL.height / 2,
    bottom: LABEL.height / 2,
  });
  const numberAt = (x: number): ScreenBox => ({
    left: x - 12,
    right: x + 12,
    top: -12,
    bottom: 12,
  });

  it.each([
    ['clear at the middle', [numberAt(100)], 0.5],
    ['the middle blocked, a quarter clear', [numberAt(500)], 0.25],
    [
      'the middle and a quarter blocked, three quarters clear',
      [numberAt(510), numberAt(250)],
      0.75,
    ],
    ['every candidate blocked: hidden', [numberAt(500), numberAt(250), numberAt(750)], 'hidden'],
    ['a stop number that only touches the label does not block it', [numberAt(500 + 20 + 12)], 0.5],
  ] as [string, ScreenBox[], number | 'hidden'][])('%s', (_name, numbers, expected) => {
    expect(placeRetraceLabel(labelAt, numbers)).toBe(expected);
  });

  it('is tried at the middle, then a quarter, then three quarters, along the line itself', () => {
    expect(RETRACE_FRACTIONS).toEqual([0.5, 0.25, 0.75]);
    const plan = buildRunMap(
      collection(
        line(
          [
            [7.0, 45.0],
            [7.0, 45.4],
          ],
          { kind: 'retrace' },
        ),
      ),
      CONFIG,
    );
    expect(plan.overlays[0].candidates).toEqual([
      { fraction: 0.5, lngLat: [7.0, 45.2] },
      { fraction: 0.25, lngLat: [7.0, 45.1] },
      { fraction: 0.75, lngLat: [7.0, 45.3] },
    ]);
  });

  it('never covers a numbered box with the spot it chooses (seeded)', () => {
    let seed = 20260519;
    const next = (): number => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    let hidden = 0;
    for (let round = 0; round < 500; round += 1) {
      const numbers = Array.from({ length: Math.floor(next() * 7) }, () => {
        const centre = next() * 1000;
        const half = 6 + next() * 40;
        return { left: centre - half, right: centre + half, top: -half, bottom: half };
      });
      const chosen = placeRetraceLabel(labelAt, numbers);
      if (chosen === 'hidden') {
        hidden += 1;
        continue;
      }
      const box = labelAt(chosen);
      for (const n of numbers) {
        expect(
          box.left < n.right && n.left < box.right && box.top < n.bottom && n.top < box.bottom,
        ).toBe(false);
      }
    }
    expect(hidden, 'the generated boxes hide it sometimes and not always').toBeGreaterThan(0);
    expect(hidden).toBeLessThan(500);
  });
});

describe('the map before any route (D288)', () => {
  const item = (overrides: Partial<Item>): Item => ({
    id: 'i',
    type: 'poi',
    name: 'Susa',
    included: true,
    anchor: null,
    location: { lat: 45.14, lon: 7.05 },
    entry: null,
    exit: null,
    length_m: null,
    ...overrides,
  });
  const trail = item({
    id: 't',
    type: 'track',
    name: 'Assietta',
    location: null,
    entry: { lat: 45.05, lon: 7.04 },
    exit: { lat: 44.95, lon: 6.88 },
  });

  it.each([
    ['start', 'Start'],
    ['end', 'End'],
    ['start_end', 'Start/End'],
    [null, ''],
  ] as const)('draws a place saved as %s as a dot with the tag "%s"', (anchor, tag) => {
    const { overlays } = buildTripMap([item({ anchor })], CONFIG);

    expect(overlays).toEqual([{ kind: 'place', text: tag, title: 'Susa', lngLat: [7.05, 45.14] }]);
  });

  it("draws a trail by its entry and its exit alone, as the run's markers are, and fits everything", () => {
    const plan = buildTripMap([item({}), trail], CONFIG);

    expect(plan.overlays.map((o) => [o.kind, o.title, o.lngLat])).toEqual([
      ['place', 'Susa', [7.05, 45.14]],
      ['entry', 'Entry of Assietta', [7.04, 45.05]],
      ['exit', 'Exit of Assietta', [6.88, 44.95]],
    ]);
    expect(plan.bounds).toEqual([
      [6.88, 44.95],
      [7.05, 45.14],
    ]);
  });

  it('has no bounds for an empty trip, and keeps the base map, Terrain and credit layers of a run map', () => {
    const empty = buildTripMap([], CONFIG, true);
    const run = buildRunMap(collection(), CONFIG, true);

    expect(empty.bounds).toBeNull();
    expect(empty.overlays).toEqual([]);
    expect(empty.style.layers.map((l) => l.id)).toEqual(run.style.layers.map((l) => l.id));
    expect(empty.style.layers.find((l) => l.id === TERRAIN_LAYER)).toMatchObject({
      layout: { visibility: 'visible' },
    });
  });
});

describe('selecting a stop (D286)', () => {
  const TRAIL: [number, number][] = [
    [7.0, 45.0],
    [7.2, 45.1],
  ];
  const BACK: [number, number][] = [
    [7.2, 45.1],
    [6.9, 45.05],
  ];
  const geometry = collection(
    line(ROAD, { kind: 'road', stop: 2 }),
    line(TRAIL, { kind: 'track', stop: 3 }),
    line(BACK, { kind: 'retrace', stop: 4 }),
    marker([7.0, 45.0], { marker: 'start_end', stop: 1, end_stop: 5 }),
    marker([7.0, 45.0], { marker: 'entry', stop: 3 }),
    marker([6.9, 45.05], { marker: 'stop', stop: 4 }),
  );

  it.each([
    [
      'a road leg and what belongs to the stop',
      2,
      [
        [7.0, 45.0],
        [7.0, 45.4],
      ],
    ],
    [
      'a trail, its entry marker',
      3,
      [
        [7.0, 45.0],
        [7.2, 45.1],
      ],
    ],
    [
      "a retrace's own line and its own marker",
      4,
      [
        [6.9, 45.05],
        [7.2, 45.1],
      ],
    ],
    [
      'the End of a round trip, through the S/E marker',
      5,
      [
        [7.0, 45.0],
        [7.0, 45.0],
      ],
    ],
    [
      'the Start of a round trip, through the S/E marker',
      1,
      [
        [7.0, 45.0],
        [7.0, 45.0],
      ],
    ],
    ['a stop nothing is drawn for', 9, null],
  ])('fits %s: stop %i', (_what, stop, expected) => {
    expect(stopBounds(geometry, stop)).toEqual(expected);
  });

  it('keeps a stop selected at full opacity and every other line at 35 %, nothing dimmed when none is selected', () => {
    expect(DIMMED_OPACITY).toBe(0.35);
    expect(stopOpacity(undefined)).toBe(1);
    const expression = stopOpacity(3);
    expect(expression).toEqual(['case', ['==', ['get', 'stop'], 3], 1, DIMMED_OPACITY]);
  });

  it('dims the lines, their casings and the track arrows, each by its own paint property', () => {
    const plan = buildRunMap(geometry, CONFIG);
    const ids = plan.style.layers.map((candidate) => candidate.id);
    for (const [layerId, property] of DIMMED_PAINTS) {
      expect(ids).toContain(layerId);
      expect(property).toBe(layerId === 'track-arrows' ? 'icon-opacity' : 'line-opacity');
    }
    expect(DIMMED_PAINTS.map(([layerId]) => layerId)).toEqual(
      expect.arrayContaining([
        'road-confirmed',
        'road-confirmed-casing',
        'retrace',
        'track-arrows',
      ]),
    );
  });

  it("names the road and track colours once, for the card's edge marks", () => {
    const plan = buildRunMap(geometry, CONFIG);
    const paint = (id: string) => (layer(plan, id)?.paint as Record<string, unknown>)['line-color'];
    expect(paint('road-confirmed')).toBe(ROAD_COLOUR);
    expect(paint('track')).toBe(TRACK_COLOUR);
  });
});
