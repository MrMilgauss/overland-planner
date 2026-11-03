// The planner's HTTP API (same origin; the browser's own Basic-auth prompt covers the shared password). Every /api
// error is an envelope {code, message} whose message is shown to Marco verbatim (PlannerError.message).

export interface Project {
  id: string;
  name: string;
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

export class PlannerError extends Error {}

const GENERIC_FAILURE = 'Could not load projects. Please try again.';
const GENERIC_WRITE_FAILURE = 'The planner could not do this. Please try again.';

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
  if (!response.ok) throw new PlannerError(messageFrom(body) ?? failure);
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
