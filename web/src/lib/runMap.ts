// The run map as data (slice 09, step 10-04, ADR-003 Amendment 2): the planner's geometry answer and the map settings
// in, a MapLibre style (tiles, the lines, their layers), the text and marker overlays, and the bounds out. Pure: the
// drawing itself (WebGL) is RunMap.svelte's, and the web composes no wording but the labels of the map itself.
import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from 'maplibre-gl';

export const ARROW_IMAGE = 'direction-arrow';

/** GET /api/config/map. */
export interface MapConfig {
  tile_url: string;
  attribution: string;
  max_zoom: number;
}

type LngLat = [number, number];

export interface LineProperties {
  kind: 'road' | 'track' | 'retrace';
  stop: number;
  item_id: string;
  name: string;
  level: 'confirmed' | 'unconfirmed' | null;
  reason: string | null;
  geometry: 'available' | 'unavailable';
}

export interface MarkerProperties {
  marker: 'stop' | 'entry' | 'exit' | 'start_end' | 'start' | 'end';
  stop: number;
  item_id: string;
  name: string;
  end_stop: number | null;
}

export interface LineFeature {
  type: 'Feature';
  geometry: { type: 'LineString'; coordinates: LngLat[] };
  properties: LineProperties;
}

export interface MarkerFeature {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: LngLat };
  properties: MarkerProperties;
}

/** GET /api/plan-runs/{id}/geometry: the lines in itinerary order, then the markers. */
export interface RunGeometry {
  type: 'FeatureCollection';
  features: (LineFeature | MarkerFeature)[];
}

/** Something HTML on the map: a numbered stop, an entry or exit, or a text on a line. */
export interface MapOverlay {
  kind: MarkerProperties['marker'] | 'unconfirmed' | 'retrace' | 'unavailable';
  text: string;
  title: string;
  lngLat: LngLat;
  /** A retrace label's candidate places along its line, in the order they are tried. */
  candidates?: { fraction: number; lngLat: LngLat }[];
}

export interface RunMapPlan {
  style: StyleSpecification;
  overlays: MapOverlay[];
  /** South-west and north-east corners that hold every feature; none for an empty run. */
  bounds: [LngLat, LngLat] | null;
}

const ROAD_BLUE = '#1d4ed8';
const UNCONFIRMED_ORANGE = '#ea580c';
const RETRACE_PURPLE = '#7e22ce';
const TRACK_GREEN = '#14532d';
const UNAVAILABLE_GREY = '#6b7280';
const LINE_WIDTH = 4;
// Arrows and their spacing follow the zoom (D269): small and far apart for the whole trip on a phone, full size and
// close together on a trail. Zoom 8 shows a trip of some hundred km on 390 px; zoom 13 is a trail.
const TRIP_ZOOM = 8;
const TRAIL_ZOOM = 13;
const ARROW_SIZES = [0.5, 1];
const ARROW_SPACINGS = [160, 80];
const DISPLAY_DECIMALS = 1e6;
/** A click this close to an entry or exit marker (inclusive) means that marker's place. */
export const SNAP_PIXELS = 12;

const is = (property: string, value: string): ExpressionSpecification => [
  '==',
  ['get', property],
  value,
];
const drawn = (...tests: ExpressionSpecification[]): ExpressionSpecification => ['all', ...tests];

const zoomed = ([trip, trail]: number[]): ExpressionSpecification => [
  'interpolate',
  ['linear'],
  ['zoom'],
  TRIP_ZOOM,
  trip,
  TRAIL_ZOOM,
  trail,
];

function lineLayer(
  id: string,
  filter: ExpressionSpecification,
  color: string,
  dash?: number[],
): LayerSpecification {
  return {
    id,
    type: 'line',
    source: 'run',
    filter,
    layout: { 'line-cap': dash ? 'butt' : 'round', 'line-join': 'round' },
    paint: {
      'line-color': color,
      'line-width': LINE_WIDTH,
      ...(dash ? { 'line-dasharray': dash } : {}),
    },
  };
}

const ARROW_SIZE = 24;
const WHITE = [255, 255, 255, 255];
const GREEN = [20, 83, 45, 255];

/** Is the pixel inside the triangle of the three corners (all given the same way round)? */
function inside(x: number, y: number, [a, b, c]: [number, number][]): boolean {
  const side = (p: [number, number], q: [number, number]): number =>
    (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]);
  const signs = [side(a, b), side(b, c), side(c, a)];
  return signs.every((value) => value >= 0) || signs.every((value) => value <= 0);
}

/** The direction arrow, pointing right (a line's own direction when placed along it): a green head with a white
 * edge, as pixels: no sprite file and no canvas to draw on. */
export function arrowImage(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(ARROW_SIZE * ARROW_SIZE * 4);
  const edge: [number, number][] = [
    [3, 3],
    [21, 12],
    [3, 21],
  ];
  const head: [number, number][] = [
    [6, 7],
    [16, 12],
    [6, 17],
  ];
  for (let y = 0; y < ARROW_SIZE; y += 1) {
    for (let x = 0; x < ARROW_SIZE; x += 1) {
      const colour = inside(x + 0.5, y + 0.5, head)
        ? GREEN
        : inside(x + 0.5, y + 0.5, edge)
          ? WHITE
          : undefined;
      if (colour) data.set(colour, (y * ARROW_SIZE + x) * 4);
    }
  }
  return { width: ARROW_SIZE, height: ARROW_SIZE, data };
}

function layersOf(config: MapConfig): LayerSpecification[] {
  const available = is('geometry', 'available');
  return [
    {
      id: 'tiles',
      type: 'raster',
      source: 'tiles',
      maxzoom: config.max_zoom + 1,
    } as LayerSpecification,
    lineLayer('unavailable', is('geometry', 'unavailable'), UNAVAILABLE_GREY, [2, 2]),
    lineLayer(
      'road-confirmed',
      drawn(is('kind', 'road'), is('level', 'confirmed'), available),
      ROAD_BLUE,
    ),
    lineLayer(
      'road-unconfirmed',
      drawn(is('kind', 'road'), is('level', 'unconfirmed'), available),
      UNCONFIRMED_ORANGE,
      [0.5, 2],
    ),
    lineLayer('retrace', drawn(is('kind', 'retrace'), available), RETRACE_PURPLE, [8, 4]),
    lineLayer('track', drawn(is('kind', 'track'), available), TRACK_GREEN),
    {
      id: 'track-arrows',
      type: 'symbol',
      source: 'run',
      filter: drawn(is('kind', 'track'), available),
      layout: {
        'symbol-placement': 'line',
        'symbol-spacing': zoomed(ARROW_SPACINGS),
        'icon-image': ARROW_IMAGE,
        'icon-size': zoomed(ARROW_SIZES),
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
      },
    },
  ];
}

function isLine(feature: LineFeature | MarkerFeature): feature is LineFeature {
  return feature.geometry.type === 'LineString';
}

const rounded = (value: number): number => Math.round(value * DISPLAY_DECIMALS) / DISPLAY_DECIMALS;

/** The point a fraction of the way along a line, by length in the plane of the map's own degrees (right for a label). */
function pointAlong(points: LngLat[], fraction: number): LngLat {
  const scale = Math.cos((points[0][1] * Math.PI) / 180);
  const lengths = points.slice(1).map((point, index) => {
    const previous = points[index];
    return Math.hypot((point[0] - previous[0]) * scale, point[1] - previous[1]);
  });
  let remaining = lengths.reduce((sum, length) => sum + length, 0) * fraction;
  for (const [index, length] of lengths.entries()) {
    if (remaining <= length || index === lengths.length - 1) {
      const t = length === 0 ? 0 : Math.min(remaining / length, 1);
      const [from, to] = [points[index], points[index + 1]];
      return [rounded(from[0] + (to[0] - from[0]) * t), rounded(from[1] + (to[1] - from[1]) * t)];
    }
    remaining -= length;
  }
  return points[0];
}

function labelOf(line: LineFeature): MapOverlay | undefined {
  const { kind, level, reason, geometry } = line.properties;
  if (line.geometry.coordinates.length === 0) return undefined; // nothing drawn, nothing to label
  const lngLat = pointAlong(line.geometry.coordinates, 0.5);
  if (geometry === 'unavailable') {
    return {
      kind: 'unavailable',
      text: 'geometry unavailable',
      title: line.properties.name,
      lngLat,
    };
  }
  if (kind === 'retrace') {
    const candidates = RETRACE_FRACTIONS.map((fraction) => ({
      fraction,
      lngLat: pointAlong(line.geometry.coordinates, fraction),
    }));
    return { kind: 'retrace', text: 'retrace', title: line.properties.name, lngLat, candidates };
  }
  if (kind === 'road' && level === 'unconfirmed') {
    return { kind: 'unconfirmed', text: '!', title: reason ?? 'Unconfirmed', lngLat };
  }
  return undefined;
}

function markerOf(feature: MarkerFeature): MapOverlay {
  const { marker, stop, end_stop: endStop, name } = feature.properties;
  const lngLat = feature.geometry.coordinates;
  const numbered = (text: string, numbers: string): MapOverlay => ({
    kind: marker,
    text,
    title: `${numbers}. ${name}`,
    lngLat,
  });
  switch (marker) {
    case 'start_end':
      return numbered(`S/E ${stop} and ${endStop}`, `${stop} and ${endStop}`);
    case 'start':
      return numbered(`S ${stop}`, `${stop}`);
    case 'end':
      return numbered(`E ${stop}`, `${stop}`);
    case 'stop':
      return numbered(`${stop}`, `${stop}`);
    case 'entry':
      return { kind: marker, text: '', title: `Entry of ${name}`, lngLat };
    case 'exit':
      return { kind: marker, text: '', title: `Exit of ${name}`, lngLat };
  }
}

function boundsOf(points: LngLat[]): [LngLat, LngLat] | null {
  if (points.length === 0) return null;
  const lngs = points.map((point) => point[0]);
  const lats = points.map((point) => point[1]);
  return [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ];
}

export function buildRunMap(geometry: RunGeometry, config: MapConfig): RunMapPlan {
  const lines = geometry.features.filter(isLine);
  const overlays = geometry.features.flatMap((feature) => {
    const overlay = isLine(feature) ? labelOf(feature) : markerOf(feature);
    return overlay ? [overlay] : [];
  });
  const points = geometry.features.flatMap((feature) =>
    isLine(feature) ? feature.geometry.coordinates : [feature.geometry.coordinates],
  );
  return {
    style: {
      version: 8,
      sources: {
        tiles: {
          type: 'raster',
          tiles: [config.tile_url],
          tileSize: 256,
          maxzoom: config.max_zoom,
          attribution: config.attribution,
        },
        run: { type: 'geojson', data: { type: 'FeatureCollection', features: lines } as never },
      },
      layers: layersOf(config),
    },
    overlays,
    bounds: boundsOf(points),
  };
}

export interface ScreenPoint {
  x: number;
  y: number;
}

/** An entry or exit marker as the screen has it now: where it is drawn and where it stands. */
export interface MarkerSpot extends ScreenPoint {
  lngLat: LngLat;
}

export interface Place {
  lat: number;
  lon: number;
}

/** The place a click on the map stands for: the exact place of the nearest entry or exit marker within SNAP_PIXELS of
 * the click, else the clicked place to 6 decimals (about 0.1 m). */
export function placeClicked(click: ScreenPoint, clickedAt: LngLat, markers: MarkerSpot[]): Place {
  const gap = (marker: MarkerSpot): number => Math.hypot(marker.x - click.x, marker.y - click.y);
  const near = markers
    .filter((marker) => gap(marker) <= SNAP_PIXELS)
    .sort((a, b) => gap(a) - gap(b))[0];
  if (near) return { lat: near.lngLat[1], lon: near.lngLat[0] };
  return { lat: rounded(clickedAt[1]), lon: rounded(clickedAt[0]) };
}

/** A box on the screen, in pixels. */
export interface ScreenBox {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** Where along a retrace line its label may stand, in the order tried: the middle, then a quarter, then three quarters. */
export const RETRACE_FRACTIONS = [0.5, 0.25, 0.75];

const overlaps = (a: ScreenBox, b: ScreenBox): boolean =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

/** The first candidate place whose label box covers no numbered marker (D270); 'hidden' when every one does, until the
 * map is zoomed in. `labelAt` gives the label's screen box at a fraction of the line's length. */
export function placeRetraceLabel(
  labelAt: (fraction: number) => ScreenBox,
  numbered: ScreenBox[],
): number | 'hidden' {
  const clear = RETRACE_FRACTIONS.find(
    (fraction) => !numbered.some((box) => overlaps(labelAt(fraction), box)),
  );
  return clear ?? 'hidden';
}
