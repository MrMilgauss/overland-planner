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
function stubPlanner(items: Item[][], replies: Record<string, Reply | Reply[]> = {}): Call[] {
  const calls: Call[] = [];
  let itemReads = 0;
  const served: Record<string, number> = {};
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      calls.push({ method, url, body: init.body });
      const key = `${method} ${url}`;
      let reply: Reply;
      if (key in replies) {
        const given = replies[key];
        const at = (served[key] = (served[key] ?? -1) + 1); // a list answers in turn, the last one stays
        reply = Array.isArray(given) ? given[Math.min(at, given.length - 1)] : given;
      } else if (key === 'GET /api/projects/p1') reply = { status: 200, body: PROJECT };
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

// US-28: the coverage of the trip is read after every change of it; what lies outside is tagged, and warned once when it
// became outside; a map the page cannot read invents nothing.
const REGIONS = ['Italy', 'Spain'];
const covered = (outside: string[], known = true): Reply => ({
  status: 200,
  body: {
    known,
    map_date: '2026-11-27T12:00:00Z',
    regions: known ? REGIONS : [],
    outside_item_ids: outside,
    groups: [],
  },
});
const coverageReads = (calls: Call[]): number =>
  calls.filter((c) => c.method === 'GET' && c.url === '/api/projects/p1/coverage').length;
const WARNING =
  "Chefchaouen is outside the planner's road map (Italy and Spain). It is kept, but it can't be planned unless its region is added on the Road map screen";

describe('Workspace page: coverage', () => {
  it('shows the box on opening, with no alert for what was outside before', async () => {
    stubPlanner([[place('i1', 'Chefchaouen')]], {
      'GET /api/projects/p1/coverage': {
        ...covered(['i1']),
        body: { ...(covered(['i1']).body as object), regions: ['Spain', 'Italy'] }, // by name
      },
      'GET /api/road-map': {
        status: 200,
        body: {
          served: { known: true, map_date: null, regions: [{ name: 'Italy' }, { name: 'Spain' }] },
          change: { state: 'none', start_at: null, added: [], removed: [] },
        },
      },
    });

    render(WorkspacePage, { props: { projectId: 'p1' } });

    // the road map's own order, not the coverage's
    expect(await screen.findByText('Roads loaded for: Italy and Spain')).toBeInTheDocument();
    expect(screen.getByText('Map data: 27 November 2026')).toBeInTheDocument();
    expect(screen.getByText('Outside road map')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reads the coverage again after a change and warns once for the item that became outside, dismissibly', async () => {
    const calls = stubPlanner([[], [place('i1', 'Chefchaouen')]], {
      'GET /api/projects/p1/coverage': [covered([]), covered(['i1'])],
      'POST /api/projects/p1/pois': { status: 201, body: place('i1', 'Chefchaouen') },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByText('Roads loaded for: Italy and Spain');
    expect(coverageReads(calls)).toBe(1);

    await typeAPlace('Chefchaouen', '35.1688', '-5.2636');

    expect(await screen.findByRole('alert')).toHaveTextContent(WARNING);
    expect(screen.getByText('Outside road map')).toBeInTheDocument();
    expect(coverageReads(calls)).toBe(2);
    await fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Outside road map')).toBeInTheDocument();
  });

  it('keeps a dismissed warning dismissed when a later reading fails and the next one still has the item outside', async () => {
    const chefchaouen = place('i1', 'Chefchaouen');
    const calls = stubPlanner([[], [chefchaouen], [chefchaouen], [chefchaouen]], {
      'GET /api/projects/p1/coverage': [
        covered([]),
        covered(['i1']),
        { status: 500, body: { code: 'x', message: 'no' } },
        covered(['i1']),
      ],
      'POST /api/projects/p1/pois': { status: 201, body: chefchaouen },
      'PUT /api/projects/p1/anchors': { status: 200, body: { ...PROJECT, revision: 2 } },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByText('Roads loaded for: Italy and Spain');
    await typeAPlace('Chefchaouen', '35.1688', '-5.2636');
    await fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }));

    await setFromTheRow('Chefchaouen', 'Set as start');
    await setFromTheRow('Chefchaouen', 'Set as end'); // this reading fails
    await vi.waitFor(() => expect(coverageReads(calls)).toBe(3));
    await setFromTheRow('Chefchaouen', 'Set as start');
    await setFromTheRow('Chefchaouen', 'Set as end'); // the next one has the item outside again
    await vi.waitFor(() => expect(coverageReads(calls)).toBe(4));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each([
    { case: 'a map without a record', reply: covered(['i1'], false) },
    {
      case: 'a coverage the page cannot read',
      reply: { status: 500, body: { code: 'x', message: 'no' } },
    },
  ])('$case: says "Map coverage unknown" at most, no list, no tag, no alert', async ({ reply }) => {
    stubPlanner([[place('i1', 'Chefchaouen')]], { 'GET /api/projects/p1/coverage': reply });

    render(WorkspacePage, { props: { projectId: 'p1' } });
    await itemNamed('Chefchaouen');

    expect(await screen.findByText('Map coverage unknown')).toBeInTheDocument();
    expect(screen.queryByText(/Roads loaded for/)).not.toBeInTheDocument();
    expect(screen.queryByText('Outside road map')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('warns once for each outside trail of a file import', async () => {
    const trail = (id: string, name: string) => ({ ...place(id, name), type: 'track' as const });
    const trails = [trail('t1', 'algarve'), trail('t2', 'lisboa')];
    stubPlanner([[], trails], {
      'GET /api/projects/p1/coverage': [covered([]), covered(['t1', 't2'])],
      'POST /api/projects/p1/tracks': { status: 201, body: trails },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await screen.findByText('Roads loaded for: Italy and Spain');
    const files = ['algarve.gpx', 'lisboa.gpx'].map((n) => new File(['<gpx/>'], n));

    await fireEvent.change(screen.getByLabelText('GPX files'), { target: { files } });

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.map((a) => a.textContent)).toEqual([
      expect.stringContaining('algarve is outside the planner'),
      expect.stringContaining('lisboa is outside the planner'),
    ]);
  });

  it.each([
    {
      case: 'two land groups: Build the trip warns',
      groups: [
        { regions: ['Italy', 'Spain'], item_ids: ['i1'] },
        { regions: ['Utah'], item_ids: ['i2'] },
      ],
      warned: true,
    },
    {
      case: 'one land group: nothing',
      groups: [{ regions: ['Italy'], item_ids: ['i1'] }],
      warned: false,
    },
  ])('$case', async ({ groups, warned }) => {
    stubPlanner([[place('i1', 'Torino'), place('i2', 'Moab')]], {
      'GET /api/projects/p1/coverage': {
        status: 200,
        body: { ...(covered([]).body as object), groups },
      },
    });

    render(WorkspacePage, { props: { projectId: 'p1' } });

    await screen.findByText('Roads loaded for: Italy and Spain');
    expect(screen.queryByText(/not linked by land/) !== null).toBe(warned);
  });
});

describe('Workspace page: search for a place (US-29)', () => {
  const settings = (place_search: boolean): Reply => ({
    status: 200,
    body: {
      tile_url: 'x',
      attribution: 'x',
      max_zoom: 17,
      base_style_url: 'x',
      base_attribution: 'x',
      place_search,
    },
  });
  const entries = async (): Promise<(string | null)[]> => {
    await fireEvent.click(await screen.findByRole('button', { name: 'Add' }));
    return within(document.getElementById('add-options')!)
      .getAllByRole('button')
      .map((b) => b.textContent);
  };

  it('offers four ways to add when the map settings say place search is on', async () => {
    stubPlanner([[]], { 'GET /api/config/map': settings(true) });
    render(WorkspacePage, { props: { projectId: 'p1' } });

    expect(await entries()).toEqual([
      'Upload GPX trails',
      'Click on the map',
      'Type coordinates',
      'Search for a place',
    ]);
  });

  it('offers the three ways to add when the map settings say place search is off', async () => {
    stubPlanner([[]], { 'GET /api/config/map': settings(false) });
    render(WorkspacePage, { props: { projectId: 'p1' } });

    expect(await entries()).toEqual(['Upload GPX trails', 'Click on the map', 'Type coordinates']);
  });

  it('adds a found place through the add-place call, the form staying open', async () => {
    const calls = stubPlanner([[], [place('i1', 'Gorges du Verdon')]], {
      'GET /api/config/map': settings(true),
      'GET /api/places/search?q=Gorges%20du%20Verdon': {
        status: 200,
        body: [
          {
            name: 'Gorges du Verdon',
            region: 'PACA',
            country: 'France',
            lat: 43.7686,
            lon: 6.3322,
          },
        ],
      },
      'POST /api/projects/p1/pois': { status: 201, body: place('i1', 'Gorges du Verdon') },
    });
    render(WorkspacePage, { props: { projectId: 'p1' } });
    await entries();
    await fireEvent.click(screen.getByRole('button', { name: 'Search for a place' }));
    await fireEvent.input(screen.getByLabelText('Place name'), {
      target: { value: 'Gorges du Verdon' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    const row = await screen.findByText('Gorges du Verdon, PACA, France');

    await fireEvent.click(within(row.closest('li')!).getByRole('button', { name: 'Add' }));

    expect(await itemNamed('Gorges du Verdon')).toBeInTheDocument();
    expect(writes(calls).map((c) => JSON.parse(c.body as string))).toEqual([
      { name: 'Gorges du Verdon', lat: 43.7686, lon: 6.3322 },
    ]);
    expect(screen.getByRole('form', { name: 'Search for a place' })).toBeVisible();
  });
});

describe('Workspace page while the road map changes', () => {
  const SERVED = { known: true, map_date: '2026-11-27T12:00:00Z', regions: [], total_bytes: 0 };
  const LIMITS = {
    max_gb: 8,
    max_bytes: 8_000_000_000,
    next_rebuild_from: null,
    changes_available: true,
    rebuilds_set_up: true,
    helper_seen_at: null,
  };
  const roadMap = (change: unknown, back: string | null): Record<string, Reply> => ({
    'GET /api/road-map': {
      status: 200,
      body: {
        served: SERVED,
        change,
        limits: LIMITS,
        planning_paused: back !== null,
        planning_back_at: back,
        server_utc_offset_minutes: 0,
      },
    },
  });
  const TRIP = [place('i1', 'Torino', 'start_end')];

  it('tells a planned rebuild on the project and keeps Plan the route on', async () => {
    stubPlanner(
      [TRIP],
      roadMap({ state: 'planned', start_at: '2030-12-02T01:00:00Z', added: [], removed: [] }, null),
    );
    render(WorkspacePage, { props: { projectId: 'p1' } });

    expect(await screen.findByText(/^Rebuild planned for /)).toBeVisible();
    expect(await screen.findByRole('button', { name: 'Plan the route' })).toBeEnabled();
  });

  it('disables Plan the route from the build to the switch, with the line', async () => {
    stubPlanner(
      [TRIP],
      roadMap(
        {
          state: 'running',
          step: 'building',
          steps_done: 2,
          start_at: null,
          added: [],
          removed: [],
        },
        '2026-11-27T21:48:00Z',
      ),
    );
    render(WorkspacePage, { props: { projectId: 'p1' } });

    const line = await screen.findAllByText(
      /^The road map is being rebuilt; planning is back at about \d\d:\d\d\.$/,
    );
    expect(line.length).toBeGreaterThan(0);
    expect(await screen.findByRole('button', { name: 'Plan the route' })).toBeDisabled();
    expect(await itemNamed('Torino')).toBeVisible();
  });

  it('asks the planner again every 10 seconds while a change runs, and enables planning when it ends', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const building = {
        state: 'running',
        step: 'building',
        steps_done: 2,
        start_at: null,
        added: [],
        removed: [],
      };
      const replies = roadMap(building, '2026-11-27T21:48:00Z');
      stubPlanner([TRIP], replies);
      render(WorkspacePage, { props: { projectId: 'p1' } });
      await vi.advanceTimersByTimeAsync(0);
      await vi.waitFor(() =>
        expect(screen.getByRole('button', { name: 'Plan the route' })).toBeDisabled(),
      );

      stubPlanner([TRIP], roadMap({ state: 'none', start_at: null, added: [], removed: [] }, null));
      await vi.advanceTimersByTimeAsync(10_000);
      await vi.waitFor(() =>
        expect(screen.getByRole('button', { name: 'Plan the route' })).toBeEnabled(),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps asking every 10 seconds after a failed read while a change runs, and enables planning when it ends', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const building = {
        state: 'running',
        step: 'building',
        steps_done: 2,
        start_at: null,
        added: [],
        removed: [],
      };
      stubPlanner([TRIP], roadMap(building, '2026-11-27T21:48:00Z'));
      render(WorkspacePage, { props: { projectId: 'p1' } });
      await vi.advanceTimersByTimeAsync(0);
      await vi.waitFor(() =>
        expect(screen.getByRole('button', { name: 'Plan the route' })).toBeDisabled(),
      );

      stubPlanner([TRIP], { 'GET /api/road-map': { status: 503, body: {} } });
      await vi.advanceTimersByTimeAsync(10_000);
      stubPlanner([TRIP], roadMap({ state: 'none', start_at: null, added: [], removed: [] }, null));
      await vi.advanceTimersByTimeAsync(10_000);
      await vi.waitFor(() =>
        expect(screen.getByRole('button', { name: 'Plan the route' })).toBeEnabled(),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('reads the coverage and the road map once more when the change ends, so the box names the new regions and date', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const running = {
        state: 'running',
        step: 'switching',
        steps_done: 3,
        start_at: null,
        added: [],
        removed: [],
      };
      const body = (served: unknown, change: unknown) => ({
        status: 200,
        body: {
          served,
          change,
          limits: LIMITS,
          planning_paused: false,
          planning_back_at: null,
          server_utc_offset_minutes: 0,
        },
      });
      const old = { known: true, map_date: '2026-11-27T12:00:00Z', regions: [{ name: 'Italy' }] };
      stubPlanner([TRIP], {
        'GET /api/road-map': body(old, running),
        'GET /api/projects/p1/coverage': covered([]),
      });
      render(WorkspacePage, { props: { projectId: 'p1' } });
      await vi.advanceTimersByTimeAsync(0);
      await vi.waitFor(() => expect(screen.getByText('Roads loaded for: Italy')).toBeVisible());

      const now = {
        known: true,
        map_date: '2026-11-28T01:00:00Z',
        regions: [{ name: 'Italy' }, { name: 'Portugal' }],
      };
      const calls = stubPlanner([TRIP], {
        'GET /api/projects/p1/coverage': covered([]),
        'GET /api/road-map': body(now, {
          state: 'done',
          start_at: null,
          added: [],
          removed: [],
          result: { code: null, message: 'Road map rebuilt', finished_at: '2026-11-28T01:56:00Z' },
        }),
      });
      await vi.advanceTimersByTimeAsync(10_000);
      await vi.waitFor(() =>
        expect(screen.getByText('Roads loaded for: Italy and Portugal')).toBeVisible(),
      );
      expect(screen.getByText('Map data: 28 November 2026')).toBeVisible();
      const reads = () => calls.filter((c) => c.url === '/api/road-map').length;
      const before = reads();
      await vi.advanceTimersByTimeAsync(60_000);
      expect(reads()).toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });
});
