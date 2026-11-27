// The trip map as data (ADR-003 Amendment 2): the planner's geometry answer and the map
// settings in, a MapLibre style (tiles, the lines, their layers), the text and marker overlays, and the bounds out; or,
// before any route, the trip's items. Pure: the drawing itself (WebGL) is TripMap.svelte's, and the web composes no
// wording but the labels of the map itself.
import type { Item } from './api';
import type {
  ExpressionSpecification,
  LayerSpecification,
  SourceSpecification,
  StyleSpecification,
} from 'maplibre-gl';

export const ARROW_IMAGE = 'direction-arrow';

/** GET /api/config/map. */
export interface MapConfig {
  tile_url: string;
  attribution: string;
  max_zoom: number;
  base_style_url: string;
  base_attribution: string;
  /** Whether the Add menu offers "Search for a place" (the PLACE_SEARCH setting). */
  place_search: boolean;
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
  kind: MarkerProperties['marker'] | 'unconfirmed' | 'retrace' | 'unavailable' | 'place';
  /** The itinerary stops a numbered marker stands for: its own, and the End's too for a round trip's S/E marker. */
  stops?: number[];
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

export const ROAD_COLOUR = '#1d4ed8';
const UNCONFIRMED_ORANGE = '#ea580c';
const RETRACE_PURPLE = '#7e22ce';
export const TRACK_COLOUR = '#14532d';
const UNAVAILABLE_GREY = '#6b7280';
// Line widths follow the zoom like the arrows (D287): 4 px for the whole trip, 7 px on a trail, each on a white casing
// 3 px wider so that the route stands out on any base map.
const LINE_WIDTHS = [4, 7];
const UNAVAILABLE_DASH = [2, 2];
const UNCONFIRMED_DASH = [0.5, 2];
const RETRACE_DASH = [8, 4];
const TILE_SIZE = 256;
const CASING_EXTRA = 3;
const CASING_WHITE = '#ffffff';
/** The layers the map itself adds between the base map and the route (D287). */
export const PLAIN_BACKGROUND_LAYER = 'plain-background';
export const CREDIT_LAYER = 'base-credit';
export const TERRAIN_LAYER = 'terrain';
const CREDIT_SOURCE = 'base-credit';
const PLAIN_BACKGROUND = '#f2f2ef';
// Arrows and their spacing follow the zoom (D269): small and far apart for the whole trip on a phone, full size and
// close together on a trail. Zoom 8 shows a trip of some hundred km on 390 px; zoom 13 is a trail.
const TRIP_ZOOM = 8;
const TRAIL_ZOOM = 13;
const ARROW_SIZES = [0.5, 1];
const ARROW_SPACINGS = [160, 80];
const MIDDLE = 0.5; // half way along a line, by length
/** Where along a retrace line its label may stand, in the order tried: the middle, then a quarter, then three quarters. */
export const RETRACE_FRACTIONS = [MIDDLE, 0.25, 0.75];
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

function lineLayers(
  id: string,
  filter: ExpressionSpecification,
  color: string,
  dash?: number[],
): LayerSpecification[] {
  const layout = { 'line-cap': dash ? 'butt' : 'round', 'line-join': 'round' } as const;
  return [
    {
      id: `${id}-casing`,
      type: 'line',
      source: 'run',
      filter,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': CASING_WHITE,
        'line-width': zoomed(LINE_WIDTHS.map((width) => width + CASING_EXTRA)),
      },
    },
    {
      id,
      type: 'line',
      source: 'run',
      filter,
      layout,
      paint: {
        'line-color': color,
        'line-width': zoomed(LINE_WIDTHS),
        ...(dash ? { 'line-dasharray': dash } : {}),
      },
    },
  ];
}

const ARROW_SIZE = 24; // pixels, square
const PIXEL_CENTRE = 0.5; // the pixel (x, y) is the point (x + 0.5, y + 0.5)
const ARROW_WHITE = [255, 255, 255, 255];
const ARROW_GREEN = [20, 83, 45, 255];

/** Is the pixel inside the triangle of the three corners (all given the same way round)? */
function inside(x: number, y: number, [a, b, c]: [number, number][]): boolean {
  const side = (p: [number, number], q: [number, number]): number =>
    (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]);
  const signs = [side(a, b), side(b, c), side(c, a)];
  return signs.every((value) => value >= 0) || signs.every((value) => value <= 0);
}

// The two triangles of the arrow, in its own 24 px square: the white edge around the green head.
const ARROW_EDGE: [number, number][] = [
  [3, 3],
  [21, 12],
  [3, 21],
];
const ARROW_HEAD: [number, number][] = [
  [6, 7],
  [16, 12],
  [6, 17],
];

/** The direction arrow, pointing right (a line's own direction when placed along it): a green head with a white
 * edge, as pixels: no sprite file and no canvas to draw on. */
export function arrowImage(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(ARROW_SIZE * ARROW_SIZE * 4);
  for (let y = 0; y < ARROW_SIZE; y += 1) {
    for (let x = 0; x < ARROW_SIZE; x += 1) {
      const [px, py] = [x + PIXEL_CENTRE, y + PIXEL_CENTRE];
      const colour = inside(px, py, ARROW_HEAD)
        ? ARROW_GREEN
        : inside(px, py, ARROW_EDGE)
          ? ARROW_WHITE
          : undefined;
      if (colour) data.set(colour, (y * ARROW_SIZE + x) * 4);
    }
  }
  return { width: ARROW_SIZE, height: ARROW_SIZE, data };
}

function layersOf(config: MapConfig, terrain: boolean): LayerSpecification[] {
  const available = is('geometry', 'available');
  return [
    // Until the light base map is adopted, and for good when it cannot be had, the route stands on a plain background.
    {
      id: PLAIN_BACKGROUND_LAYER,
      type: 'background',
      paint: { 'background-color': PLAIN_BACKGROUND },
    },
    {
      id: CREDIT_LAYER,
      type: 'line',
      source: CREDIT_SOURCE,
      layout: { visibility: 'none' },
    },
    {
      id: TERRAIN_LAYER,
      type: 'raster',
      source: 'tiles',
      maxzoom: config.max_zoom + 1,
      layout: { visibility: terrain ? 'visible' : 'none' },
    } as LayerSpecification,
    ...lineLayers('unavailable', is('geometry', 'unavailable'), UNAVAILABLE_GREY, UNAVAILABLE_DASH),
    ...lineLayers(
      'road-confirmed',
      drawn(is('kind', 'road'), is('level', 'confirmed'), available),
      ROAD_COLOUR,
    ),
    ...lineLayers(
      'road-unconfirmed',
      drawn(is('kind', 'road'), is('level', 'unconfirmed'), available),
      UNCONFIRMED_ORANGE,
      UNCONFIRMED_DASH,
    ),
    ...lineLayers('retrace', drawn(is('kind', 'retrace'), available), RETRACE_PURPLE, RETRACE_DASH),
    ...lineLayers('track', drawn(is('kind', 'track'), available), TRACK_COLOUR),
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
  const lngLat = pointAlong(line.geometry.coordinates, MIDDLE);
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

const END_TITLES = { entry: 'Entry', exit: 'Exit' } as const;

/** A trail's entry or exit: a bare marker, titled with the trail's name. */
const endOverlay = (kind: keyof typeof END_TITLES, name: string, lngLat: LngLat): MapOverlay => ({
  kind,
  text: '',
  title: `${END_TITLES[kind]} of ${name}`,
  lngLat,
});

function markerOf(feature: MarkerFeature): MapOverlay {
  const { marker, stop, end_stop: endStop, name } = feature.properties;
  const lngLat = feature.geometry.coordinates;
  const numbered = (text: string, numbers: string, stops: number[]): MapOverlay => ({
    kind: marker,
    text,
    title: `${numbers}. ${name}`,
    lngLat,
    stops,
  });
  switch (marker) {
    case 'start_end':
      return numbered(`S/E ${stop} and ${endStop}`, `${stop} and ${endStop}`, [
        stop,
        ...(endStop === null ? [] : [endStop]),
      ]);
    case 'start':
      return numbered(`S ${stop}`, `${stop}`, [stop]);
    case 'end':
      return numbered(`E ${stop}`, `${stop}`, [stop]);
    case 'stop':
      return numbered(`${stop}`, `${stop}`, [stop]);
    case 'entry':
      return endOverlay('entry', name, lngLat);
    case 'exit':
      return endOverlay('exit', name, lngLat);
  }
}

/** Every coordinate a feature draws: a line's points, or a marker's one. */
const pointsOf = (feature: LineFeature | MarkerFeature): LngLat[] =>
  isLine(feature) ? feature.geometry.coordinates : [feature.geometry.coordinates];

function boundsOf(points: LngLat[]): [LngLat, LngLat] | null {
  if (points.length === 0) return null;
  const lngs = points.map((point) => point[0]);
  const lats = points.map((point) => point[1]);
  return [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ];
}

/** The box around every line and marker of one itinerary stop (a round trip's S/E marker belongs to its End too); none
 * when nothing is drawn for it. */
export function stopBounds(geometry: RunGeometry, stop: number): [LngLat, LngLat] | null {
  const points = geometry.features
    .filter(
      (feature) =>
        feature.properties.stop === stop ||
        ('end_stop' in feature.properties && feature.properties.end_stop === stop),
    )
    .flatMap(pointsOf);
  return boundsOf(points);
}

/** The lines other than the selected stop's are drawn at this opacity (D286). */
export const DIMMED_OPACITY = 0.35;

/** The opacity of every route line while `stop` is selected: full for its own lines, dimmed for the rest. */
export function stopOpacity(stop: number | undefined): number | ExpressionSpecification {
  return stop === undefined ? 1 : ['case', ['==', ['get', 'stop'], stop], 1, DIMMED_OPACITY];
}

/** Every layer a selection dims, with the paint property that holds its opacity. */
export const DIMMED_PAINTS: [string, string][] = [
  'unavailable',
  'road-confirmed',
  'road-unconfirmed',
  'retrace',
  'track',
]
  .flatMap((id) => [
    [id, 'line-opacity'] as [string, string],
    [`${id}-casing`, 'line-opacity'] as [string, string],
  ])
  .concat([['track-arrows', 'icon-opacity']]);

/** The map's own style: a plain background, the Terrain tiles (hidden unless `terrain`) and the route; never blank. */
export function buildRunMap(geometry: RunGeometry, config: MapConfig, terrain = false): RunMapPlan {
  const lines = geometry.features.filter(isLine);
  const overlays = geometry.features.flatMap((feature) => {
    const overlay = isLine(feature) ? labelOf(feature) : markerOf(feature);
    return overlay ? [overlay] : [];
  });
  const points = geometry.features.flatMap(pointsOf);
  return {
    style: {
      version: 8,
      sources: {
        tiles: {
          type: 'raster',
          tiles: [config.tile_url],
          tileSize: TILE_SIZE,
          maxzoom: config.max_zoom,
          attribution: config.attribution,
        },
        run: { type: 'geojson', data: { type: 'FeatureCollection', features: lines } as never },
        [CREDIT_SOURCE]: {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
          attribution: config.base_attribution,
        },
      },
      layers: layersOf(config, terrain),
    },
    overlays,
    bounds: boundsOf(points),
  };
}

const PLACE_TAGS = { start: 'Start', end: 'End', start_end: 'Start/End' } as const;
/** The view of an empty trip: the western Alps. */
export const DEFAULT_VIEW: { center: LngLat; zoom: number } = { center: [6.9, 44.9], zoom: 7 };

function itemOverlays(item: Item): MapOverlay[] {
  if (item.type === 'poi') {
    if (!item.location) return [];
    const lngLat: LngLat = [item.location.lon, item.location.lat];
    const text = item.anchor ? PLACE_TAGS[item.anchor] : '';
    return [{ kind: 'place', text, title: item.name, lngLat }];
  }
  const ends: MapOverlay[] = [];
  if (item.entry) ends.push(endOverlay('entry', item.name, [item.entry.lon, item.entry.lat]));
  if (item.exit) ends.push(endOverlay('exit', item.name, [item.exit.lon, item.exit.lat]));
  return ends;
}

/** The map before any route (D288): the run map's own style with no route in it, and the trip's items as overlays: a
 * place a dot with its Start or End tag, a trail its entry and its exit (its shape is not drawn). */
export function buildTripMap(items: Item[], config: MapConfig, terrain = false): RunMapPlan {
  const overlays = items.flatMap(itemOverlays);
  const { style } = buildRunMap({ type: 'FeatureCollection', features: [] }, config, terrain);
  return { style, overlays, bounds: boundsOf(overlays.map((overlay) => overlay.lngLat)) };
}

/** The fetched light base map with the map's own sources and layers kept after every base layer (labels included), as
 * MapLibre's `transformStyle` hands them: the base map's glyphs and sprite stay, the plain background goes, and the
 * credit is the planner's own words (the light base map's sources say an empty credit). */
export function adoptBaseStyle(
  own: StyleSpecification,
  base: StyleSpecification,
  terrain: boolean,
): StyleSpecification {
  // An empty credit, not an absent one: a source given by a TileJSON address would show that file's credit beside ours.
  const uncredited = Object.fromEntries(
    Object.entries(base.sources).map(([name, source]) => [
      name,
      { ...source, attribution: '' } as unknown as SourceSpecification,
    ]),
  );
  const ours = own.layers
    .filter((layer) => layer.id !== PLAIN_BACKGROUND_LAYER)
    .map((layer) =>
      layer.id === CREDIT_LAYER
        ? { ...layer, layout: { visibility: terrain ? 'none' : 'visible' } }
        : layer,
    ) as LayerSpecification[];
  const kept = new Set(ours.map((layer) => layer.id));
  return {
    ...base,
    sources: { ...uncredited, ...own.sources },
    layers: [...base.layers.filter((layer) => !kept.has(layer.id)), ...ours],
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
