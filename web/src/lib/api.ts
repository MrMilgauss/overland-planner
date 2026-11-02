export interface Project {
  id: string;
  name: string;
}

export class PlannerError extends Error {}

const GENERIC_FAILURE = 'Could not load projects. Please try again.';

function messageFrom(body: unknown): string | undefined {
  if (typeof body === 'object' && body !== null && 'message' in body) {
    const { message } = body;
    if (typeof message === 'string' && message.trim() !== '') return message;
  }
  return undefined;
}

export async function listProjects(): Promise<Project[]> {
  let response: Response;
  try {
    response = await fetch('/api/projects', { headers: { Accept: 'application/json' } });
  } catch {
    throw new PlannerError(GENERIC_FAILURE);
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw new PlannerError(messageFrom(body) ?? GENERIC_FAILURE);
  if (!Array.isArray(body)) throw new PlannerError(GENERIC_FAILURE);
  return body as Project[];
}
