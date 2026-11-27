// The planner's HTTP API (same origin; the browser's own Basic-auth prompt covers the shared password). Every /api
// error is an envelope {code, message} whose message is shown to Marco verbatim (PlannerError.message).

import type { MapConfig, RunGeometry } from './runMap';

export type Objective = 'distance' | 'time';

export interface Project {
  id: string;
  name: string;
  /** Absent in an answer older than the objective. */
  objective?: Objective;
}

export interface Point {
  lat: number;
  lon: number;
}

export type Anchor = 'start' | 'end' | 'start_end';

/** A catalog item (D107): `location` for a POI; `entry`, `exit` and `length_m` for a track. */
export interface Item {
  id: string;
  type: 'track' | 'poi';
  name: string;
  included: boolean;
  anchor: Anchor | null;
  location: Point | null;
  entry: Point | null;
  exit: Point | null;
  length_m: number | null;
}

export interface NewPlace {
  name: string;
  lat: number;
  lon: number;
}

export type RoadLevel = 'confirmed' | 'unconfirmed';

/** One stop (FR-6.1), km and seconds unrounded; a run stored before the per-stop columns (05-07) shows them null, and
 * `track_km` and `offroad_s` are null on a place. */
export interface PlanStop {
  name: string;
  type: 'track' | 'poi' | 'retrace';
  leg_km: number | null;
  leg_s: number | null;
  cumulative_km: number | null;
  cumulative_s: number | null;
  track_km: number | null;
  offroad_s: number | null;
  entry: Point | null;
  exit: Point | null;
  /** A retrace row's own level and reason, and the level of the road leg into any other stop (slice 03b); a run
   * stored before them has none. */
  confidence?: RoadLevel | null;
  reason?: string | null;
  leg_confidence?: RoadLevel | null;
  leg_reason?: string | null;
}

/** The plan's road, off-road and total driving (FR-6.2), unrounded: rounding is the web's. */
export interface PlanTotals {
  road_km: number;
  road_s: number;
  offroad_km: number;
  offroad_s: number;
  total_km: number;
  total_s: number;
}

/** Why a Failed run has no plan, in product words (D206). */
export interface PlanReport {
  reason: string;
}

export interface PlanRun {
  id: string;
  number: number;
  status: 'ready' | 'failed';
  stale?: boolean; // the project changed since the run was computed
}

/** Why a ready run is not fully optimised; the words are in the run's `messages` (D223 b). */
export type NotFullyOptimised = 'optimizer_failed' | 'time_limit' | 'stopped';

/** A plan run with its stops and totals; a Failed run has neither, names its `failure_reason` code and its `report`.
 * A run stored before the totals (0006) shows `totals` null; one stored before the report (05-08) `report` null.
 * `messages` are the planner's own lines, in order (run time, label, reuse, failure), shown verbatim; `memo_hit` says
 * the run reused an identical earlier plan. */
export interface PlanRunDetail extends PlanRun {
  project_id: string;
  failure_reason: string | null;
  stops: PlanStop[];
  totals: PlanTotals | null;
  report: PlanReport | null;
  not_fully_optimised?: NotFullyOptimised | null;
  messages?: string[];
  memo_hit?: boolean;
  /** Provider header and objective of the run; absent on a run stored before them. */
  provider_header?: string | null;
  /** True when the roads are the offline road map: the plan is an estimate (D267). */
  estimate: boolean;
  objective?: Objective | null;
  objective_label?: string | null;
}

export type PlanJobState =
  | 'queued'
  | 'computing_legs'
  | 'waiting_for_optimizer'
  | 'solving'
  | 'finalising'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'timed_out';

/** The last valid route of a solve: `objective` is road metres for `distance`, road seconds for `time`. */
export interface Incumbent {
  unconfirmed_legs: number;
  retraces: number;
  objective: number;
  found_at_s: number;
}

/** `stoppable` until the job is finalising (ADR-015); an ended job's `message` says what it did, in words. */
export interface PlanJob {
  state: PlanJobState;
  reason: string | null;
  message: string | null;
  plan_run_id: string | null;
  elapsed_s: number;
  memo_hit?: boolean;
  ignore_memo?: boolean;
  stoppable?: boolean;
  notices?: string[];
  incumbent?: Incumbent | null;
}

export interface PlanJobAccepted {
  job_id: string;
  notices?: string[];
}

/** A count of all time and of the window. */
export interface WindowCount {
  all_time: number;
  window: number;
}

/** GET /api/diagnostics (kpi-contracts `diagnostics_endpoint`) over the last `days` days; seconds unrounded. */
export interface Diagnostics {
  version: string;
  process_started_at: string;
  days: number;
  k2: { invariant_violations: WindowCount };
  k3: { report_omissions: WindowCount };
  k5: {
    stage_p95_s: Record<string, number | null>;
    solve_p95_s: Record<string, number | null>;
    e2e_p95_s: number | null;
    e2e_p95_by_band_s: Record<string, number | null>;
    e2e_source: string;
    retried_jobs: Record<string, number>;
    second_pass_gt_700_jobs: Record<string, number>;
    failed_jobs: Record<string, number>;
    cancelled_jobs: Record<string, number>;
    memo_hit_jobs: Record<string, number>;
  };
  k7: { runs_per_project_day: { median: number | null; max: number | null } };
  /** Plan requests refused for a routing engine that was unreachable or not ready, over the window asked for. */
  g4: { engine_refusals_30d: number };
  jobs_by_terminal_state_30d: Record<string, number>;
  retried_jobs_30d: number;
  second_pass_jobs_30d: number;
}

/** `status` is the HTTP status of the planner's refusal; none when the planner could not be reached. */
export class PlannerError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

const GENERIC_FAILURE = 'Could not load projects. Please try again.';
const GENERIC_WRITE_FAILURE = 'The planner could not do this. Please try again.';
const PLAN_READ_FAILURE = 'Could not load the plan.';

/** What Marco reads about a failed call: the planner's own message when it gave one. */
export function failureText(error: unknown): string {
  return error instanceof PlannerError ? error.message : GENERIC_WRITE_FAILURE;
}

function messageFrom(body: unknown): string | undefined {
  if (typeof body === 'object' && body !== null && 'message' in body) {
    const { message } = body;
    if (typeof message === 'string' && message.trim() !== '') return message;
  }
  return undefined;
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

async function call<T>(url: string, init: RequestInit, failure: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, ...init });
  } catch {
    throw new PlannerError(failure);
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw new PlannerError(messageFrom(body) ?? failure, response.status);
  if (body === undefined) throw new PlannerError(failure);
  return body as T;
}

export async function listProjects(): Promise<Project[]> {
  const body = await call<unknown>('/api/projects', {}, GENERIC_FAILURE);
  if (!Array.isArray(body)) throw new PlannerError(GENERIC_FAILURE);
  return body as Project[];
}

export function createProject(name: string): Promise<Project> {
  return call('/api/projects', json('POST', { name }), GENERIC_WRITE_FAILURE);
}

export function openProject(projectId: string): Promise<Project> {
  return call(`/api/projects/${encodeURIComponent(projectId)}`, {}, 'Could not open the project.');
}

/** Changes the project's objective; the planner answers the project as it now is. */
export function setObjective(projectId: string, objective: Objective): Promise<Project> {
  return call(
    `/api/projects/${encodeURIComponent(projectId)}`,
    json('PATCH', { objective }),
    GENERIC_WRITE_FAILURE,
  );
}

export async function listItems(projectId: string): Promise<Item[]> {
  const failure = 'Could not load the trails and places.';
  const body = await call<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/items`,
    {},
    failure,
  );
  if (!Array.isArray(body)) throw new PlannerError(failure);
  return body as Item[];
}

export function importTracks(projectId: string, files: File[]): Promise<Item[]> {
  const form = new FormData();
  for (const file of files) form.append('files', file, file.name);
  return call(
    `/api/projects/${encodeURIComponent(projectId)}/tracks`,
    { method: 'POST', body: form },
    GENERIC_WRITE_FAILURE,
  );
}

export function addPlace(projectId: string, place: NewPlace): Promise<Item> {
  return call(
    `/api/projects/${encodeURIComponent(projectId)}/pois`,
    json('POST', place),
    GENERIC_WRITE_FAILURE,
  );
}

/** One place of a search (GET /api/places/search): its region and country say which one it is. */
export interface PlaceHit extends NewPlace {
  region: string;
  country: string;
}

const SEARCH_UNAVAILABLE =
  "The place search isn't answering. Try again in a minute, or add the place another way.";

/** Up to five places for the typed words. A refusal of the words (422) keeps the planner's message; a search that is
 * busy, down or unreachable is one message of the page's own. */
export async function searchPlaces(words: string): Promise<PlaceHit[]> {
  let body: unknown;
  try {
    body = await call<unknown>(
      `/api/places/search?q=${encodeURIComponent(words)}`,
      {},
      SEARCH_UNAVAILABLE,
    );
  } catch (error) {
    if (error instanceof PlannerError && error.status !== undefined && error.status < 500)
      throw error;
    throw new PlannerError(
      SEARCH_UNAVAILABLE,
      error instanceof PlannerError ? error.status : undefined,
    );
  }
  if (!Array.isArray(body)) throw new PlannerError(SEARCH_UNAVAILABLE);
  return body as PlaceHit[];
}

/** Takes an item (a trail or a place) off the trip; the planner clears a Start or End that pointed at it. */
export async function removeItem(projectId: string, itemId: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/items/${encodeURIComponent(itemId)}`,
      { method: 'DELETE', headers: { Accept: 'application/json' } },
    );
  } catch {
    throw new PlannerError(GENERIC_WRITE_FAILURE);
  }
  if (response.ok) return;
  const body: unknown = await response.json().catch(() => undefined);
  throw new PlannerError(messageFrom(body) ?? GENERIC_WRITE_FAILURE, response.status);
}

export function setAnchors(
  projectId: string,
  startItemId: string,
  endItemId: string,
): Promise<Project> {
  return call(
    `/api/projects/${encodeURIComponent(projectId)}/anchors`,
    json('PUT', { start_item_id: startItemId, end_item_id: endItemId }),
    GENERIC_WRITE_FAILURE,
  );
}

/** Calculate; `ignoreMemo` (Re-optimise) starts a fresh search instead of reusing an identical earlier plan. */
export function startPlan(projectId: string, ignoreMemo = false): Promise<PlanJobAccepted> {
  const query = ignoreMemo ? '?ignore_memo=true' : '';
  return call(
    `/api/projects/${encodeURIComponent(projectId)}/plan-runs${query}`,
    { method: 'POST' },
    GENERIC_WRITE_FAILURE,
  );
}

export function readPlanJob(jobId: string): Promise<PlanJob> {
  return call(`/api/plan-jobs/${encodeURIComponent(jobId)}`, {}, PLAN_READ_FAILURE);
}

/** Stop and use best so far; the planner treats a repeated Stop as the same one. */
export function stopPlanJob(jobId: string): Promise<PlanJob> {
  return call(
    `/api/plan-jobs/${encodeURIComponent(jobId)}/stop`,
    { method: 'POST' },
    GENERIC_WRITE_FAILURE,
  );
}

export function readDiagnostics(): Promise<Diagnostics> {
  return call('/api/diagnostics', {}, 'Could not load the diagnostics.');
}

export function listPlanRuns(projectId: string): Promise<PlanRun[]> {
  return call(`/api/projects/${encodeURIComponent(projectId)}/plan-runs`, {}, PLAN_READ_FAILURE);
}

export function readPlanRun(planRunId: string): Promise<PlanRunDetail> {
  return call(`/api/plan-runs/${encodeURIComponent(planRunId)}`, {}, PLAN_READ_FAILURE);
}

/** The Terrain tiles, credit and top zoom, and the light base map's style and credit, as the settings choose them. */
export function readMapConfig(): Promise<MapConfig> {
  return call('/api/config/map', {}, 'Could not load the map settings.');
}

/** One region of the served map (GET /api/road-map): its size is what its map data weighs. */
export interface ServedRegion {
  key: string;
  name: string;
  parent_name: string | null;
  bytes: number;
}

/** The regions the engine serves; `known` is false when the planner cannot tell (GET /api/road-map). */
export interface ServedRoadMap {
  served: {
    known: boolean;
    map_date: string | null;
    regions: ServedRegion[];
    total_bytes: number;
  };
}

export function readRoadMap(): Promise<ServedRoadMap> {
  return call('/api/road-map', {}, 'Could not read the road map.');
}

/** One region of the free list (GET /api/road-map/catalogue): `bytes` is null while its size cannot be told. */
export interface CatalogueRegion {
  key: string;
  name: string;
  parent_name: string | null;
  bytes: number | null;
  in_map: boolean;
}

const CATALOGUE_UNAVAILABLE = 'The list of regions cannot be reached right now - try again later';

/** Up to eight regions for the typed words; the planner's refusal (under two letters, list down) keeps its words. */
export async function searchRegions(words: string): Promise<CatalogueRegion[]> {
  const body = await call<{ results?: unknown }>(
    `/api/road-map/catalogue?q=${encodeURIComponent(words)}`,
    {},
    CATALOGUE_UNAVAILABLE,
  );
  if (!Array.isArray(body.results)) throw new PlannerError(CATALOGUE_UNAVAILABLE);
  return body.results as CatalogueRegion[];
}

/** What a change would say before it is applied: only the information line is used on the screen so far. */
export interface ChangePreview {
  not_linked_note: string | null;
}

/** The summary of holding exactly these regions (POST /api/road-map/change/preview); nothing is written. */
export function previewChange(regionKeys: string[]): Promise<ChangePreview> {
  return call(
    '/api/road-map/change/preview',
    json('POST', { region_keys: regionKeys }),
    'Could not check this change.',
  );
}

/** A trip judged against the served map (GET /api/projects/{id}/coverage): `outside_item_ids` lie outside the loaded
 * regions, and `known` is false when the planner cannot tell (then regions and outside items are empty). */
export interface TripCoverage {
  known: boolean;
  map_date: string | null;
  regions: string[];
  outside_item_ids: string[];
  groups: { regions: string[]; item_ids: string[] }[];
}

export function readCoverage(projectId: string): Promise<TripCoverage> {
  return call(
    `/api/projects/${encodeURIComponent(projectId)}/coverage`,
    {},
    'Could not read the map coverage.',
  );
}

/** The lines and markers of a ready run, in the planner's own words when it refuses (a Failed run has no route). */
export function readRunGeometry(planRunId: string): Promise<RunGeometry> {
  return call(
    `/api/plan-runs/${encodeURIComponent(planRunId)}/geometry`,
    {},
    'Could not load the map of the run.',
  );
}

/** The file of a ready plan run; the planner's answer names it. */
export function planRunExportUrl(planRunId: string): string {
  return `/api/plan-runs/${encodeURIComponent(planRunId)}/export.gpx`;
}

/** The banners of GET /api/health (D108), whatever its status; none when the planner cannot be asked (the page
 * then shows its own error). */
export async function healthBanners(): Promise<string[]> {
  try {
    const response = await fetch('/api/health', { headers: { Accept: 'application/json' } });
    const body: unknown = await response.json();
    const banners: unknown =
      typeof body === 'object' && body !== null && 'banners' in body ? body.banners : [];
    return Array.isArray(banners) ? banners.filter((b): b is string => typeof b === 'string') : [];
  } catch {
    return [];
  }
}
