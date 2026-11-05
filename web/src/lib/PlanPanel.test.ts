// The plan of a project (slice 01b): Calculate, polling every 500 ms, the Itinerary and Export GPX, each job state and
// each refusal. The fetch stub stands in for the planner's HTTP API (the port of the page); only setTimeout is faked,
// so the polling clock is the test's.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 04-10); the job's states are property-tested on
// the server (steps 04-04, 04-09), and the journey runs in a real browser (test_slice_01b.py).
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PlanPanel from './PlanPanel.svelte';

type Reply = { status: number; body: unknown } | 'network down';
type Routes = Record<string, Reply | Reply[]>;

const RUNS = '/api/projects/p1/plan-runs';
const JOB = '/api/plan-jobs/j1';
const NO_RUNS: Reply = { status: 200, body: [] };
const ACCEPTED: Reply = { status: 202, body: { job_id: 'j1' } };
const CASA = { name: 'Casa Marco, Torino', type: 'poi', leg_km: null, entry: null, exit: null };

function job(state: string, fields: Record<string, unknown> = {}): Reply {
  return {
    status: 200,
    body: { state, reason: null, message: null, plan_run_id: null, elapsed_s: 1.5, ...fields },
  };
}

function listed(...runs: [string, number, string][]): Reply {
  return { status: 200, body: runs.map(([id, number, status]) => ({ id, number, status })) };
}

function readyRun(id: string, number: number, stopName = 'Briancon'): Reply {
  const stop = { ...CASA, name: stopName, leg_km: 12.25 };
  return {
    status: 200,
    body: {
      id,
      project_id: 'p1',
      number,
      status: 'ready',
      failure_reason: null,
      stops: [CASA, stop],
    },
  };
}

function failedRun(id: string, number: number, reason: string): Reply {
  return {
    status: 200,
    body: { id, project_id: 'p1', number, status: 'failed', failure_reason: reason, stops: [] },
  };
}

/** A planner answering by "METHOD path"; a list of replies answers in turn and then keeps repeating its last. */
function stubPlanner(routes: Routes): string[] {
  const calls: string[] = [];
  const turns: Record<string, number> = {};
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const key = `${init.method ?? 'GET'} ${url}`;
      calls.push(key);
      const route = routes[key];
      let reply: Reply = { status: 404, body: { code: 'not_found', message: `unexpected ${key}` } };
      if (Array.isArray(route)) {
        const turn = turns[key] ?? 0;
        turns[key] = turn + 1;
        reply = route[Math.min(turn, route.length - 1)];
      } else if (route) reply = route;
      if (reply === 'network down') throw new TypeError('Failed to fetch');
      return new Response(JSON.stringify(reply.body), { status: reply.status });
    }),
  );
  return calls;
}

function count(calls: string[], key: string): number {
  return calls.filter((call) => call === key).length;
}

/** Lets every answer already on its way arrive, so that what follows reads the page as it now is. */
async function settled(): Promise<void> {
  for (let turn = 0; turn < 10; turn += 1) await new Promise((done) => setImmediate(done));
}

async function clickCalculate(): Promise<void> {
  await settled();
  await fireEvent.click(screen.getByRole('button', { name: 'Calculate' }));
}

async function pressCalculate(): Promise<void> {
  await clickCalculate();
  await settled();
}

async function tick(ms = 500): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
  await settled();
}

function exportLink(): HTMLElement | null {
  return screen.queryByRole('link', { name: 'Export GPX' });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Plan panel: calculating', () => {
  it.each([
    ['queued', 'Queued'],
    ['computing_legs', 'Computing legs'],
    ['waiting_for_optimizer', 'Waiting for the optimizer'],
    ['solving', 'Solving'],
    ['finalising', 'Finalising'],
  ])('shows the running state %s as %s, with Calculate disabled', async (state, text) => {
    stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job(state),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();

    expect(screen.getByRole('status')).toHaveTextContent(text);
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeDisabled();
    expect(exportLink()).not.toBeInTheDocument();
  });

  it('asks for the job every 500 ms while it runs', async () => {
    const calls = stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('solving'),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    screen.getByRole('status');
    await tick(499);
    expect(count(calls, `GET ${JOB}`)).toBe(0);
    await tick(1);
    expect(count(calls, `GET ${JOB}`)).toBe(1);
    await tick(500);
    expect(count(calls, `GET ${JOB}`)).toBe(2);
  });

  it('shows the stops and offers Export GPX when the job ends with a ready run, and stops asking', async () => {
    const calls = stubPlanner({
      [`GET ${RUNS}`]: [NO_RUNS, listed(['r1', 1, 'ready'])],
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: [job('solving'), job('done', { plan_run_id: 'r1' })],
      'GET /api/plan-runs/r1': readyRun('r1', 1),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();
    await tick();

    const itinerary = screen.getByRole('list', { name: 'Itinerary' });
    expect(within(itinerary).getAllByRole('listitem')).toHaveLength(2);
    expect(within(itinerary).getByText('12.2 km')).toBeInTheDocument();
    const link = exportLink();
    expect(link).toHaveAttribute('href', '/api/plan-runs/r1/export.gpx');
    expect(link).not.toHaveAttribute('download');
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    const asked = count(calls, `GET ${JOB}`);
    await tick(2000);
    expect(count(calls, `GET ${JOB}`)).toBe(asked);
  });

  it('stops asking when the page goes away, also if it leaves before the job is accepted', async () => {
    const calls = stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('solving'),
    });
    const running = render(PlanPanel, { props: { projectId: 'p1' } });
    await pressCalculate();
    screen.getByRole('status');
    await tick();
    const asked = count(calls, `GET ${JOB}`);
    expect(asked).toBe(1);

    running.unmount();
    await tick(2000);
    expect(count(calls, `GET ${JOB}`)).toBe(asked);

    const leaving = render(PlanPanel, { props: { projectId: 'p1' } });
    await clickCalculate();
    leaving.unmount();
    await tick(2000);
    expect(count(calls, `GET ${JOB}`)).toBe(asked);
  });
});

describe('Plan panel: refusals and failures', () => {
  it.each([
    [422, 'missing_anchor', 'Set a Start and an End first'],
    [409, 'job_active', 'A calculation is already running for this project'],
    [503, 'optimizer_unavailable', 'The optimizer is not available right now'],
  ])('shows a %d refusal verbatim and leaves Calculate usable', async (status, code, message) => {
    const calls = stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: { status, body: { code, message } },
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();

    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    await tick(2000);
    expect(count(calls, `GET ${JOB}`)).toBe(0);
  });

  it('shows the message of a job in state failed, offers no export and stops asking', async () => {
    const message = 'The plan could not be calculated - nothing was changed';
    const calls = stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('failed', { reason: 'internal', message }),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();

    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(exportLink()).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
    await tick(2000);
    expect(count(calls, `GET ${JOB}`)).toBe(1);
  });

  it('shows a Failed run with its reason and offers no export', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: [NO_RUNS, listed(['r1', 1, 'failed'])],
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('done', { reason: 'no_valid_route_found', plan_run_id: 'r1' }),
      'GET /api/plan-runs/r1': failedRun('r1', 1, 'no_valid_route_found'),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();

    expect(screen.getByRole('alert')).toHaveTextContent(
      'This plan run failed (no_valid_route_found)',
    );
    expect(exportLink()).not.toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Itinerary' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
  });

  it('keeps asking through a lost connection, with Calculate usable, until the job answers again', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: [NO_RUNS, listed(['r1', 1, 'ready'])],
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: [
        'network down',
        job('solving'),
        'network down',
        job('done', { plan_run_id: 'r1' }),
      ],
      'GET /api/plan-runs/r1': readyRun('r1', 1),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the plan.');
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();

    await tick();
    screen.getByText('Solving');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeDisabled();

    await tick();
    await tick();
    expect(screen.getByRole('list', { name: 'Itinerary' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('stops asking when the job has expired, shows why and leaves Calculate usable', async () => {
    const message = 'No plan job j1';
    const calls = stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: { status: 404, body: { code: 'not_found', message } },
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();

    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    await tick(2000);
    expect(count(calls, `GET ${JOB}`)).toBe(1);
  });
});

describe('Plan panel: reopening a project', () => {
  it('shows nothing of a plan when the project has no runs', async () => {
    stubPlanner({ [`GET ${RUNS}`]: NO_RUNS });

    render(PlanPanel, { props: { projectId: 'p1' } });

    await settled();
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
    expect(screen.queryByRole('list', { name: 'Itinerary' })).not.toBeInTheDocument();
    expect(exportLink()).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the highest-numbered ready run, whatever the order of the list', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready'], ['r3', 3, 'ready'], ['r2', 2, 'failed']),
      'GET /api/plan-runs/r3': readyRun('r3', 3, 'Aosta'),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    const itinerary = screen.getByRole('list', { name: 'Itinerary' });
    expect(within(itinerary).getByText('Aosta')).toBeInTheDocument();
    expect(screen.getByText('Run 3')).toBeInTheDocument();
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r3/export.gpx');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps showing the ready run under the failure of a later run', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready'], ['r2', 2, 'failed']),
      'GET /api/plan-runs/r1': readyRun('r1', 1),
      'GET /api/plan-runs/r2': failedRun('r2', 2, 'optimizer_failed'),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    expect(screen.getByRole('list', { name: 'Itinerary' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('This plan run failed (optimizer_failed)');
    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r1/export.gpx');
  });

  it('shows the message when the runs cannot be read, and Calculate stays usable', async () => {
    const message = 'The planner is restarting';
    stubPlanner({ [`GET ${RUNS}`]: { status: 500, body: { code: 'internal', message } } });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
  });
});
