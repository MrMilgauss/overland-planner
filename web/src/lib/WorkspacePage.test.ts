// Workspace of one project (step 03-10, 12-04): the Add menu (import trails, type a place's decimal degrees), Start and
// End from the list's rows. The fetch
// stub stands in for the planner's HTTP API (the port of the page); every error envelope message is shown verbatim.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); coordinate ranges and anchor rules are
// property-tested at the domain level (steps 03-08, 03-09).
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WorkspacePage from './WorkspacePage.svelte';
import type { Item } from './api';

// The map has its own tests (TripMap.svelte.test.ts, tests/e2e/run-map.spec.ts); here it draws nothing and records its props.
const map = vi.hoisted(() => ({
  props: undefined as
    | {
        planRunId?: string;
        items: Item[];
        onplaceadded?: () => void;
        clickMode?: boolean;
        canAdd?: boolean;
        selectedStop?: number;
        onselectstop?: (stop: number | undefined) => void;
      }
    | undefined,
}));
vi.mock('./TripMap.svelte', () => ({
  default: (_anchor: unknown, props: NonNullable<typeof map.props>) => {
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

async function typeAPlace(name: string, lat: string, lon: string): Promise<void> {
  await fireEvent.click(screen.getByRole('button', { name: 'Add' }));
  await fireEvent.click(screen.getByRole('button', { name: 'Type coordinates' }));
  await fill('Name', name);
  await fill('Latitude', lat);
  await fill('Longitude', lon);
  await fireEvent.click(
    within(screen.getByRole('form', { name: 'Type coordinates' })).getByRole('button', {
      name: 'Add',
    }),
  );
}

async function setFromTheRow(place: string, choice: 'Set as start' | 'Set as end'): Promise<void> {
  await fireEvent.click(screen.getByRole('button', { name: `Actions for ${place}` }));
  await fireEvent.click(screen.getByRole('button', { name: choice }));
}

/** The trip list's entry for `name`. */
async function itemNamed(name: string): Promise<HTMLElement> {
  return within(await screen.findByRole('list', { name: 'Your trip' })).getByText(name);
}

afterEach(() => {
  vi.unstubAllGlobals();
  map.props = undefined;
});

describe('Workspace page', () => {
  it('removes an item on confirm: one DELETE, then the list and the map are read again', async () => {
    const calls = stubPlanner(
      [[place('i1', 'Briancon'), place('i2', 'Susa')], [place('i2', 'Susa')]],
      {
        'DELETE /api/projects/p1/items/i1': { status: 204, body: undefined },
      },
    );
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await itemNamed('Briancon');

    await fireEvent.click(screen.getByRole('button', { name: 'Actions for Briancon' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

    await vi.waitFor(() => expect(screen.queryByText('Briancon')).not.toBeInTheDocument());
    expect(writes(calls).map((c) => `${c.method} ${c.url}`)).toEqual([
      'DELETE /api/projects/p1/items/i1',
    ]);
    expect(map.props?.items.map((i) => i.name)).toEqual(['Susa']);
  });

  it('shows the project name and its items', async () => {
    stubPlanner([[place('i1', 'Briancon')]]);

    render(WorkspacePage, { props: { projectId: 'p1' } });

    expect(
      await screen.findByRole('heading', { level: 1, name: PROJECT.name }),
    ).toBeInTheDocument();
    const list = await screen.findByRole('list', { name: 'Your trip' });
    expect(within(list).getByText('Briancon')).toBeInTheDocument();
  });

  it('adds a place by decimal degrees and lists it', async () => {
    const calls = stubPlanner([[], [place('i1', 'Briancon')]], {
      'POST /api/projects/p1/pois': { status: 201, body: place('i1', 'Briancon') },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByRole('heading', { level: 1, name: PROJECT.name });
    await screen.findByRole('button', { name: 'Plan the route' }); // Build the trip shows once the runs are read

    await typeAPlace('Briancon', '44.8990', '6.6430');

    const list = await screen.findByRole('list', { name: 'Your trip' });
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
    await screen.findByRole('button', { name: 'Plan the route' }); // Build the trip shows once the runs are read
    const file = new File(['<gpx/>'], 'assietta.gpx', { type: 'application/gpx+xml' });

    await fireEvent.change(screen.getByLabelText('GPX files'), { target: { files: [file] } });

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

    await setFromTheRow('Casa Marco, Torino', 'Set as start');
    await setFromTheRow('Casa Marco, Torino', 'Set as end');

    expect(await screen.findByText('End', { selector: '.tag' })).toBeInTheDocument();
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
        await typeAPlace('Briancon', '144.8990', '6.6430');
      },
    ],
    [
      'importing a file',
      'POST /api/projects/p1/tracks',
      'notes.gpx is not a valid GPX file',
      async () => {
        const notes = new File(['hello'], 'notes.gpx');
        await fireEvent.change(screen.getByLabelText('GPX files'), { target: { files: [notes] } });
      },
    ],
    [
      'setting Start and End',
      'PUT /api/projects/p1/anchors',
      'Only places (POIs) can be the Start or End',
      async () => {
        await setFromTheRow('Casa Marco, Torino', 'Set as start');
        await setFromTheRow('Casa Marco, Torino', 'Set as end');
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
    expect(
      within(screen.getByRole('list', { name: 'Your trip' })).getAllByRole('listitem'),
    ).toHaveLength(1);
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

describe('Workspace page: the "Plan for" switch', () => {
  const OBJECTIVE_PROJECT = { ...PROJECT, objective: 'distance' };
  const pressed = (name: string) =>
    screen.getByRole('button', { name }).getAttribute('aria-pressed');

  it('shows the project objective and changes it with a PATCH', async () => {
    const calls = stubPlanner([[]], {
      'GET /api/projects/p1': { status: 200, body: OBJECTIVE_PROJECT },
      'PATCH /api/projects/p1': {
        status: 200,
        body: { ...OBJECTIVE_PROJECT, objective: 'time', revision: 2 },
      },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByRole('group', { name: 'Plan for' });
    expect([pressed('Shortest distance'), pressed('Shortest time')]).toEqual(['true', 'false']);

    await fireEvent.click(screen.getByRole('button', { name: 'Shortest time' }));
    await vi.waitFor(() => expect(pressed('Shortest time')).toBe('true'));

    expect(writes(calls).map((c) => [c.method, c.url, JSON.parse(String(c.body))])).toEqual([
      ['PATCH', '/api/projects/p1', { objective: 'time' }],
    ]);
    expect(pressed('Shortest distance')).toBe('false');
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
    await screen.findByRole('group', { name: 'Plan for' });

    await fireEvent.click(screen.getByRole('button', { name: 'Shortest time' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Unknown objective');
    expect(pressed('Shortest distance')).toBe('true');
  });
});

describe('Workspace page: the map as the main column', () => {
  const RUN_LIST: Reply = { status: 200, body: [{ id: 'r1', number: 1, status: 'ready' }] };
  const RUN: Reply = {
    status: 200,
    body: { id: 'r1', project_id: 'p1', number: 1, status: 'ready', stops: [], estimate: false },
  };

  it('offers the phase steps Build the trip, Planning and Your route in that order, with one main action', async () => {
    stubPlanner([[]]);
    render(WorkspacePage, { props: { projectId: 'p1' } });

    const steps = within(await screen.findByRole('list', { name: 'Steps' })).getAllByRole(
      'listitem',
    );
    await screen.findByRole('button', { name: 'Plan the route' });

    expect(steps.map((step) => step.textContent?.replace(/^\d\s*/, '').trim())).toEqual([
      'Build the trip',
      'Planning',
      'Your route',
    ]);
    expect(screen.getByRole('region', { name: 'Build the trip' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Plan the route' })).toHaveClass('primary');
  });

  it("draws the trip's items on the map, with no placeholder, while no run is ready", async () => {
    stubPlanner([[place('i1', 'Susa')]]);
    render(WorkspacePage, { props: { projectId: 'p1' } });

    await vi.waitFor(() => expect(map.props?.items.map((item) => item.name)).toEqual(['Susa']));
    expect(map.props?.planRunId).toBeUndefined();
    expect(
      screen.queryByText('The map shows the plan once one is computed.'),
    ).not.toBeInTheDocument();
  });

  it('puts the map in its click mode when the Add menu says so', async () => {
    stubPlanner([[]]);
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByRole('button', { name: 'Add' });
    await vi.waitFor(() => expect(map.props?.clickMode).toBe(false));

    await fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Click on the map' }));

    await vi.waitFor(() => expect(map.props?.clickMode).toBe(true));
  });

  it('lets the map add places on Build the trip and on Your route, not while the trip is planned', async () => {
    stubPlanner([[]], {
      'GET /api/projects/p1/plan-runs': RUN_LIST,
      'GET /api/plan-runs/r1': RUN,
      'POST /api/projects/p1/plan-runs': { status: 202, body: { job_id: 'j1' } },
      'GET /api/plan-jobs/j1': {
        status: 200,
        body: { state: 'solving', reason: null, message: null, plan_run_id: null, elapsed_s: 1 },
      },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await vi.waitFor(() => expect(map.props?.planRunId).toBe('r1'));
    expect(map.props?.canAdd, 'Your route').toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Edit trip' }));
    await vi.waitFor(() => expect(map.props?.canAdd, 'Build the trip').toBe(true));

    await fireEvent.click(screen.getByRole('button', { name: 'Plan the route' }));
    await vi.waitFor(() => expect(map.props?.canAdd, 'Planning').toBe(false));
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
    expect(
      map.props?.planRunId,
      'the map shows the items while the trip is edited',
    ).toBeUndefined();
  });
});

describe('Workspace page: a stop selected on the itinerary or on the map (D286)', () => {
  const STOP = {
    type: 'poi',
    leg_km: 10,
    leg_s: 600,
    cumulative_km: null,
    cumulative_s: null,
    track_km: null,
    offroad_s: null,
    entry: null,
    exit: null,
  };
  const READY: Record<string, Reply> = {
    'GET /api/projects/p1/plan-runs': {
      status: 200,
      body: [{ id: 'r1', number: 1, status: 'ready' }],
    },
    'GET /api/plan-runs/r1': {
      status: 200,
      body: {
        id: 'r1',
        project_id: 'p1',
        number: 1,
        status: 'ready',
        estimate: false,
        totals: null,
        stops: [
          { ...STOP, name: 'Torino' },
          { ...STOP, name: 'Susa' },
          { ...STOP, name: 'Briancon' },
        ],
      },
    },
  };

  const steps = () =>
    within(screen.getByRole('list', { name: 'Itinerary' })).getAllByRole('button');
  const current = () => steps().map((step) => step.getAttribute('aria-current'));

  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn(); // jsdom has none
  });

  async function openReadyRoute(): Promise<void> {
    stubPlanner([[]], READY);
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await vi.waitFor(() => expect(map.props?.planRunId).toBe('r1'));
  }

  function phone(matches: boolean): ReturnType<typeof vi.fn> {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches })),
    );
    return scrolled;
  }

  it('hands the map the stop of the step pressed, and the step the stop picked on the map', async () => {
    await openReadyRoute();
    expect(map.props?.selectedStop).toBeUndefined();

    await fireEvent.click(steps()[2]);
    await vi.waitFor(() => expect(map.props?.selectedStop).toBe(3));
    expect(current()).toEqual([null, null, 'step']);

    map.props?.onselectstop?.(2);
    await vi.waitFor(() => expect(current()).toEqual([null, 'step', null]));
    expect(map.props?.selectedStop).toBe(2);

    map.props?.onselectstop?.(undefined); // Show whole route
    await vi.waitFor(() => expect(current()).toEqual([null, null, null]));
  });

  it('forgets the selection when the route goes out of the map', async () => {
    await openReadyRoute();
    await fireEvent.click(steps()[1]);
    await vi.waitFor(() => expect(map.props?.selectedStop).toBe(2));

    await fireEvent.click(screen.getByRole('button', { name: 'Edit trip' }));

    await vi.waitFor(() => expect(map.props?.planRunId).toBeUndefined());
    expect(map.props?.selectedStop).toBeUndefined();
  });

  it.each([
    [true, 1],
    [false, 0],
  ])(
    'on a phone (%s) a step press brings the map into view: %i scroll(s)',
    async (isPhone, count) => {
      const scrolled = phone(isPhone);
      await openReadyRoute();

      await fireEvent.click(steps()[1]);

      await vi.waitFor(() => expect(map.props?.selectedStop).toBe(2));
      expect(scrolled).toHaveBeenCalledTimes(count);
      if (isPhone) {
        expect(scrolled).toHaveBeenCalledWith({ block: 'nearest' });
        expect(scrolled.mock.contexts[0]).toHaveClass('stage');
      }
    },
  );
});
