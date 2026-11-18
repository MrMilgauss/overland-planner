// Workspace of one project (step 03-10): import trails, add places by decimal degrees, set Start and End. The fetch
// stub stands in for the planner's HTTP API (the port of the page); every error envelope message is shown verbatim.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); coordinate ranges and anchor rules are
// property-tested at the domain level (steps 03-08, 03-09).
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import WorkspacePage from './WorkspacePage.svelte';
import type { Item } from './api';

// The map has its own tests (RunMap.svelte.test.ts, tests/e2e/run-map.spec.ts); here it draws nothing and records its props.
const map = vi.hoisted(() => ({
  props: undefined as { planRunId: string; onplaceadded?: () => void } | undefined,
}));
vi.mock('./RunMap.svelte', () => ({
  default: (_anchor: unknown, props: { planRunId: string; onplaceadded?: () => void }) => {
    map.props = props;
  },
}));

type Reply = { status: number; body: unknown };
type Call = { method: string; url: string; body: unknown };

const PROJECT = { id: 'p1', name: 'Alpi Occidentali giugno 2027', revision: 1 };

function place(id: string, name: string, anchor: Item['anchor'] = null): Item {
  return {
    id,
    type: 'poi',
    name,
    included: true,
    anchor,
    location: { lat: 45.0703, lon: 7.6869 },
    entry: null,
    exit: null,
    length_m: null,
  };
}

/** A planner whose item list is `items`; `replies` answers the write calls by "METHOD path". */
function stubPlanner(items: Item[][], replies: Record<string, Reply> = {}): Call[] {
  const calls: Call[] = [];
  let itemReads = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      calls.push({ method, url, body: init.body });
      const key = `${method} ${url}`;
      let reply: Reply;
      if (key in replies) reply = replies[key];
      else if (key === 'GET /api/projects/p1') reply = { status: 200, body: PROJECT };
      else if (key === 'GET /api/projects/p1/items') {
        reply = { status: 200, body: items[Math.min(itemReads, items.length - 1)] };
        itemReads += 1;
      } else if (key === 'GET /api/projects/p1/plan-runs') reply = { status: 200, body: [] };
      else reply = { status: 404, body: { code: 'not_found', message: `unexpected ${key}` } };
      return new Response(JSON.stringify(reply.body), { status: reply.status });
    }),
  );
  return calls;
}

function writes(calls: Call[]): Call[] {
  return calls.filter((call) => call.method !== 'GET');
}

async function fill(label: string, value: string): Promise<void> {
  await fireEvent.input(screen.getByLabelText(label), { target: { value } });
}

/** The item list's entry for `name` (place names also appear in the Start and End choices). */
async function itemNamed(name: string): Promise<HTMLElement> {
  return within(await screen.findByRole('list', { name: 'Items' })).getByText(name);
}

afterEach(() => {
  vi.unstubAllGlobals();
  map.props = undefined;
});

describe('Workspace page', () => {
  it('shows the project name and its items', async () => {
    stubPlanner([[place('i1', 'Briancon')]]);

    render(WorkspacePage, { props: { projectId: 'p1' } });

    expect(
      await screen.findByRole('heading', { level: 1, name: PROJECT.name }),
    ).toBeInTheDocument();
    const list = await screen.findByRole('list', { name: 'Items' });
    expect(within(list).getByText('Briancon')).toBeInTheDocument();
  });

  it('adds a place by decimal degrees and lists it', async () => {
    const calls = stubPlanner([[], [place('i1', 'Briancon')]], {
      'POST /api/projects/p1/pois': { status: 201, body: place('i1', 'Briancon') },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByRole('heading', { level: 1, name: PROJECT.name });

    await fill('Place name', 'Briancon');
    await fill('Latitude', '44.8990');
    await fill('Longitude', '6.6430');
    await fireEvent.click(screen.getByRole('button', { name: 'Add place' }));

    const list = await screen.findByRole('list', { name: 'Items' });
    expect(await within(list).findByText('Briancon')).toBeInTheDocument();
    expect(writes(calls).map((c) => [c.method, c.url, JSON.parse(String(c.body))])).toEqual([
      ['POST', '/api/projects/p1/pois', { name: 'Briancon', lat: 44.899, lon: 6.643 }],
    ]);
  });

  it('imports the chosen GPX files and lists the trail', async () => {
    const assietta = { ...place('t1', "Strada dell'Assietta"), type: 'track' as const };
    const calls = stubPlanner([[], [assietta]], {
      'POST /api/projects/p1/tracks': { status: 201, body: [assietta] },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByRole('heading', { level: 1, name: PROJECT.name });
    const file = new File(['<gpx/>'], 'assietta.gpx', { type: 'application/gpx+xml' });

    await fireEvent.change(screen.getByLabelText('GPX files'), { target: { files: [file] } });
    await fireEvent.click(screen.getByRole('button', { name: 'Import' }));

    expect(await screen.findByText("Strada dell'Assietta")).toBeInTheDocument();
    const [upload] = writes(calls);
    expect([upload.method, upload.url]).toEqual(['POST', '/api/projects/p1/tracks']);
    expect((upload.body as FormData).getAll('files').map((f) => (f as File).name)).toEqual([
      'assietta.gpx',
    ]);
  });

  it('sets the chosen places as Start and End', async () => {
    const casa = place('i1', 'Casa Marco, Torino');
    const calls = stubPlanner(
      [
        [casa, place('i2', 'Aosta')],
        [place('i1', casa.name, 'start_end'), place('i2', 'Aosta')],
      ],
      {
        'PUT /api/projects/p1/anchors': { status: 200, body: { ...PROJECT, revision: 2 } },
      },
    );
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await itemNamed('Aosta');

    await fireEvent.change(screen.getByLabelText('Start'), { target: { value: 'i1' } });
    await fireEvent.change(screen.getByLabelText('End'), { target: { value: 'i1' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Set Start and End' }));

    expect(await screen.findByText('S/E')).toBeInTheDocument();
    expect(writes(calls).map((c) => [c.method, c.url, JSON.parse(String(c.body))])).toEqual([
      ['PUT', '/api/projects/p1/anchors', { start_item_id: 'i1', end_item_id: 'i1' }],
    ]);
  });

  it.each([
    [
      'adding a place',
      'POST /api/projects/p1/pois',
      'Latitude must be between -90 and 90',
      async () => {
        await fill('Place name', 'Briancon');
        await fill('Latitude', '144.8990');
        await fill('Longitude', '6.6430');
        await fireEvent.click(screen.getByRole('button', { name: 'Add place' }));
      },
    ],
    [
      'importing a file',
      'POST /api/projects/p1/tracks',
      'notes.gpx is not a valid GPX file',
      async () => {
        const notes = new File(['hello'], 'notes.gpx');
        await fireEvent.change(screen.getByLabelText('GPX files'), { target: { files: [notes] } });
        await fireEvent.click(screen.getByRole('button', { name: 'Import' }));
      },
    ],
    [
      'setting Start and End',
      'PUT /api/projects/p1/anchors',
      'Only places (POIs) can be the Start or End',
      async () => {
        await fireEvent.change(screen.getByLabelText('Start'), { target: { value: 'i1' } });
        await fireEvent.change(screen.getByLabelText('End'), { target: { value: 'i1' } });
        await fireEvent.click(screen.getByRole('button', { name: 'Set Start and End' }));
      },
    ],
  ])('shows the planner message verbatim when %s is refused', async (_case, call, message, act) => {
    stubPlanner([[place('i1', 'Casa Marco, Torino')]], {
      [call]: { status: 422, body: { code: 'validation_error', message } },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await itemNamed('Casa Marco, Torino');

    await act();

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('shows the planner message verbatim when the project cannot be opened', async () => {
    stubPlanner([[]], {
      'GET /api/projects/p1': {
        status: 404,
        body: { code: 'not_found', message: 'No project p1' },
      },
    });

    render(WorkspacePage, { props: { projectId: 'p1' } });

    expect(await screen.findByRole('alert')).toHaveTextContent('No project p1');
  });
});

describe('Workspace page: the objective', () => {
  const OBJECTIVE_PROJECT = { ...PROJECT, objective: 'distance' };

  it('shows the project objective and changes it with a PATCH', async () => {
    const calls = stubPlanner([[]], {
      'GET /api/projects/p1': { status: 200, body: OBJECTIVE_PROJECT },
      'PATCH /api/projects/p1': {
        status: 200,
        body: { ...OBJECTIVE_PROJECT, objective: 'time', revision: 2 },
      },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    const choice = (await screen.findByLabelText('Objective')) as HTMLSelectElement;
    expect(choice.value).toBe('distance');
    expect(screen.getByRole('option', { name: 'Minimise road distance' })).toBeInTheDocument();

    await fireEvent.change(choice, { target: { value: 'time' } });
    await screen.findByRole('option', { name: 'Minimise road time' });

    expect(writes(calls).map((c) => [c.method, c.url, JSON.parse(String(c.body))])).toEqual([
      ['PATCH', '/api/projects/p1', { objective: 'time' }],
    ]);
    expect((screen.getByLabelText('Objective') as HTMLSelectElement).value).toBe('time');
  });

  it('shows the planner message of a refused change and keeps the old value', async () => {
    stubPlanner([[]], {
      'GET /api/projects/p1': { status: 200, body: OBJECTIVE_PROJECT },
      'PATCH /api/projects/p1': {
        status: 422,
        body: { code: 'validation_error', message: 'Unknown objective' },
      },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    const choice = (await screen.findByLabelText('Objective')) as HTMLSelectElement;

    await fireEvent.change(choice, { target: { value: 'time' } });

    expect(await screen.findByRole('alert')).toHaveTextContent('Unknown objective');
    expect((screen.getByLabelText('Objective') as HTMLSelectElement).value).toBe('distance');
  });
});

describe('Workspace page: the map as the main column', () => {
  const RUN_LIST: Reply = { status: 200, body: [{ id: 'r1', number: 1, status: 'ready' }] };
  const RUN: Reply = {
    status: 200,
    body: { id: 'r1', project_id: 'p1', number: 1, status: 'ready', stops: [], estimate: false },
  };

  it('offers the controls in three labelled groups: Plan, Items, Start and end', async () => {
    stubPlanner([[]]);
    render(WorkspacePage, { props: { projectId: 'p1' } });

    const headings = await screen.findAllByRole('heading', { level: 2 });

    expect(headings.map((heading) => heading.textContent)).toEqual([
      'Plan',
      'Items',
      'Start and end',
    ]);
    for (const name of ['Plan', 'Items', 'Start and end']) {
      expect(screen.getByRole('region', { name })).toBeInTheDocument();
    }
  });

  it('says the map waits for a plan, and loads no map, while no run is ready', async () => {
    stubPlanner([[]]);
    render(WorkspacePage, { props: { projectId: 'p1' } });

    expect(
      await screen.findByText('The map shows the plan once one is computed.'),
    ).toBeInTheDocument();
    expect(map.props).toBeUndefined();
  });

  it('draws the ready run the panel shows, and reads items and runs again when a place is added on the map', async () => {
    const calls = stubPlanner([[], [place('i1', 'Susa')]], {
      'GET /api/projects/p1/plan-runs': RUN_LIST,
      'GET /api/plan-runs/r1': RUN,
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await vi.waitFor(() => expect(map.props?.planRunId).toBe('r1'));
    expect(
      screen.queryByText('The map shows the plan once one is computed.'),
    ).not.toBeInTheDocument();
    const runReads = () => calls.filter((c) => c.url === '/api/projects/p1/plan-runs').length;
    expect(runReads()).toBe(1);

    map.props?.onplaceadded?.();

    await itemNamed('Susa');
    await vi.waitFor(() => expect(runReads()).toBe(2));
  });
});
