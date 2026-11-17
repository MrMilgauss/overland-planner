// The plan of a project (slices 01b and 02): Calculate, polling every 500 ms, the Itinerary with its Totals and Export
// GPX, each job state, each refusal and a Failed run's report. The fetch stub stands in for the planner's HTTP API (the port of the page); only setTimeout is faked,
// so the polling clock is the test's.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11); the job's states are property-tested on
// the server (steps 04-04, 04-09), and the journey runs in a real browser (test_slice_01b.py). Slice 03 (06-11): Stop, the
// labels, messages and notices, and Re-optimise are pinned by examples here; the invariants behind them are the property
// tests of steps 06-06 to 06-10.
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PlanPanel from './PlanPanel.svelte';

type Reply = { status: number; body: unknown } | 'network down';
type Routes = Record<string, Reply | Reply[]>;
type PlannerStub = (url: string, init?: RequestInit) => Promise<Response>;

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

const TOTALS = {
  road_km: 412.25,
  road_s: 34_800,
  offroad_km: 98.75,
  offroad_s: 29_400,
  total_km: 511.0,
  total_s: 64_200,
};

function readyRun(
  id: string,
  number: number,
  stopName = 'Briancon',
  totals: typeof TOTALS | null = null,
  fields: Record<string, unknown> = {},
): Reply {
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
      totals,
      report: null,
      ...fields,
    },
  };
}

/** A Failed run names its code; one stored before the report (05-08) has none, one stored before the messages none. */
function failedRun(
  id: string,
  number: number,
  code: string,
  report: string | null = null,
  messages?: string[],
): Reply {
  return {
    status: 200,
    body: {
      id,
      project_id: 'p1',
      number,
      status: 'failed',
      failure_reason: code,
      stops: [],
      totals: null,
      report: report === null ? null : { reason: report },
      ...(messages === undefined ? {} : { messages }),
    },
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
    expect(itinerary).toHaveTextContent('12.2 km');
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

  // The planner's words for a Failed run (run_messages._FAILED), shown verbatim instead of the composed line.
  it.each([
    ['timeout', 'No valid route found within the time limit - plan run #2 failed'],
    ['stopped', 'stopped before a valid route was found'],
  ])('shows the words of a Failed %s run on a done job, not its code', async (code, words) => {
    stubPlanner({
      [`GET ${RUNS}`]: [NO_RUNS, listed(['r2', 2, 'failed'])],
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('done', { reason: code, message: words, plan_run_id: 'r2' }),
      'GET /api/plan-runs/r2': failedRun('r2', 2, code, null, [words]),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(words);
    expect(alert).not.toHaveTextContent('This plan run failed');
    expect(alert).not.toHaveTextContent(`(${code})`);
    expect(exportLink()).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
  });

  it('reads a Failed run by its report reason rather than its code', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'failed']),
      'GET /api/plan-runs/r1': failedRun(
        'r1',
        1,
        'invariant_violation',
        'internal invariant violation',
      ),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('This plan run failed (internal invariant violation)');
    expect(alert).not.toHaveTextContent('invariant_violation');
  });

  it('shows the Totals of the ready run under its itinerary', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      'GET /api/plan-runs/r1': readyRun('r1', 1, 'Briancon', TOTALS),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    const totals = screen.getByLabelText('Totals');
    expect(totals).toHaveTextContent('Road 412.2 km, 9h40');
    expect(totals).toHaveTextContent('Off-road 98.8 km, 8h10');
    expect(totals).toHaveTextContent('Total 511.0 km, 17h50');
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

describe('Plan panel: Export GPX during a recalculation', () => {
  const FIRST_RUN_READ = { 'GET /api/plan-runs/r1': readyRun('r1', 1) };

  function showsTheOldRunWithoutExport(state: string): void {
    expect(screen.getByRole('status')).toHaveTextContent(state);
    expect(exportLink()).not.toBeInTheDocument();
    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Itinerary' })).toBeInTheDocument();
  }

  /** Holds back the planner's answers to `url` until the returned function is called. */
  function holdAnswersTo(url: string): () => void {
    const planner = vi.mocked(fetch);
    const answer = planner.getMockImplementation() as unknown as PlannerStub;
    let arrive = (): void => {};
    const arrived = new Promise<void>((done) => {
      arrive = done;
    });
    const held: PlannerStub = async (asked, init) => {
      if (asked === url) await arrived;
      return answer(asked, init);
    };
    planner.mockImplementation(held as unknown as typeof fetch);
    return arrive;
  }

  it('offers no export while a job runs, keeps the itinerary on show, then offers the new run', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: [listed(['r1', 1, 'ready']), listed(['r1', 1, 'ready'], ['r2', 2, 'ready'])],
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: [job('queued'), job('solving'), job('done', { plan_run_id: 'r2' })],
      ...FIRST_RUN_READ,
      'GET /api/plan-runs/r2': readyRun('r2', 2, 'Aosta'),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r1/export.gpx');

    await pressCalculate();
    showsTheOldRunWithoutExport('Queued');
    await tick();
    showsTheOldRunWithoutExport('Queued');
    await tick();
    showsTheOldRunWithoutExport('Solving');
    await tick();

    expect(screen.getByText('Run 2')).toBeInTheDocument();
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r2/export.gpx');
  });

  it('does not offer the old run while the new one is being read', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: [listed(['r1', 1, 'ready']), listed(['r1', 1, 'ready'], ['r2', 2, 'ready'])],
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('done', { plan_run_id: 'r2' }),
      ...FIRST_RUN_READ,
      'GET /api/plan-runs/r2': readyRun('r2', 2),
    });
    const arrive = holdAnswersTo('/api/plan-runs/r2');
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();
    expect(exportLink()).not.toBeInTheDocument();

    arrive();
    await settled();
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r2/export.gpx');
  });

  it.each<[string, Reply | Reply[], Routes]>([
    [
      'a job in state failed',
      job('failed', { message: 'The plan could not be calculated - nothing was changed' }),
      {},
    ],
    [
      'a job that ended with a Failed run',
      job('done', { reason: 'no_valid_route_found', plan_run_id: 'r2' }),
      {
        [`GET ${RUNS}`]: [
          listed(['r1', 1, 'ready']),
          listed(['r1', 1, 'ready'], ['r2', 2, 'failed']),
        ],
        'GET /api/plan-runs/r2': failedRun('r2', 2, 'no_valid_route_found'),
      },
    ],
    ['a job that has expired', { status: 404, body: { code: 'not_found', message: 'No job' } }, {}],
  ])('offers the older ready run again after %s', async (_ending, jobReply, routes) => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: jobReply,
      ...FIRST_RUN_READ,
      ...routes,
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    expect(exportLink()).not.toBeInTheDocument();
    await tick();

    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r1/export.gpx');
  });

  it('offers no export through a lost connection: the job may well still run', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: 'network down',
      ...FIRST_RUN_READ,
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the plan.');
    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(exportLink()).not.toBeInTheDocument();
  });

  it('offers the older ready run again when Calculate is refused', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      [`POST ${RUNS}`]: { status: 409, body: { code: 'job_active', message: 'Already running' } },
      ...FIRST_RUN_READ,
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();

    expect(screen.getByRole('alert')).toHaveTextContent('Already running');
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r1/export.gpx');
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

describe('Plan panel: Stop and use best so far', () => {
  const STOP = `POST ${JOB}/stop`;
  const STOPPED_LABEL = 'not fully optimised (stopped)';

  function stopButton(): HTMLElement | null {
    return screen.queryByRole('button', { name: 'Stop and use best so far' });
  }

  it('offers Stop while the job is stoppable, posts it once, then shows the run', async () => {
    const calls = stubPlanner({
      [`GET ${RUNS}`]: [NO_RUNS, listed(['r1', 1, 'ready'])],
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: [
        job('solving', { stoppable: true }),
        job('done', { plan_run_id: 'r1', stoppable: false }),
      ],
      [STOP]: job('solving', { stoppable: true }),
      'GET /api/plan-runs/r1': readyRun('r1', 1, 'Briancon', null, {
        not_fully_optimised: 'stopped',
        messages: ['Planned 5 items in 2.4 s', STOPPED_LABEL],
      }),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    expect(stopButton()).not.toBeInTheDocument();
    await tick();
    const stop = stopButton();
    expect(stop).toBeEnabled();

    await fireEvent.click(stop as HTMLElement);
    await fireEvent.click(stop as HTMLElement);
    await settled();
    expect(count(calls, STOP)).toBe(1);
    expect(stop).toBeDisabled();

    await tick();
    expect(screen.getByText(STOPPED_LABEL)).toBeInTheDocument();
    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(stopButton()).not.toBeInTheDocument();
    expect(exportLink()).toHaveAttribute('href', '/api/plan-runs/r1/export.gpx');
  });

  it('does not offer Stop once the job is no longer stoppable', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('finalising', { stoppable: false }),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    await tick();

    expect(screen.getByRole('status')).toHaveTextContent('Finalising');
    expect(stopButton()).not.toBeInTheDocument();
  });

  it.each([
    ['cancelled', 'Stopped - nothing was changed'],
    ['timed_out', 'No valid route found within the time limit - nothing was changed'],
  ])(
    'shows the message of a job that ended %s without a run, and stops asking',
    async (state, message) => {
      const calls = stubPlanner({
        [`GET ${RUNS}`]: NO_RUNS,
        [`POST ${RUNS}`]: ACCEPTED,
        [`GET ${JOB}`]: [job('computing_legs', { stoppable: true }), job(state, { message })],
        [STOP]: job('computing_legs', { stoppable: true }),
      });
      render(PlanPanel, { props: { projectId: 'p1' } });

      await pressCalculate();
      await tick();
      await fireEvent.click(stopButton() as HTMLElement);
      await tick();

      expect(screen.getByText(message)).toBeInTheDocument();
      expect(stopButton()).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
      const asked = count(calls, `GET ${JOB}`);
      await tick(2000);
      expect(count(calls, `GET ${JOB}`)).toBe(asked);
    },
  );
});

describe('Plan panel: labels, messages and notices', () => {
  it.each([
    ['optimizer_failed', 'not fully optimised (optimizer failed)'],
    ['time_limit', 'not fully optimised (time limit)'],
    ['stopped', 'not fully optimised (stopped)'],
  ])('shows a run %s with its label and messages verbatim', async (code, label) => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      'GET /api/plan-runs/r1': readyRun('r1', 1, 'Briancon', null, {
        not_fully_optimised: code,
        messages: ['Planned 5 items in 2.4 s', label],
      }),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    expect(screen.getByText('Planned 5 items in 2.4 s')).toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('pins the label of a run whose optimizer failed (D223 b)', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      'GET /api/plan-runs/r1': readyRun('r1', 1, 'Briancon', null, {
        not_fully_optimised: 'optimizer_failed',
        messages: ['Planned 5 items in 2.4 s', 'not fully optimised (optimizer failed)'],
      }),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    expect(screen.getByText('not fully optimised (optimizer failed)')).toBeInTheDocument();
  });

  it("shows the job's notices while it runs and beside the run it made", async () => {
    const notice = 'Large project - calculation may take longer than 3 minutes';
    stubPlanner({
      [`GET ${RUNS}`]: [NO_RUNS, listed(['r1', 1, 'ready'])],
      [`POST ${RUNS}`]: { status: 202, body: { job_id: 'j1', notices: [notice] } },
      [`GET ${JOB}`]: [
        job('solving', { notices: [notice] }),
        job('done', { plan_run_id: 'r1', notices: [notice] }),
      ],
      'GET /api/plan-runs/r1': readyRun('r1', 1, 'Briancon', null, {
        messages: ['Planned 5 items in 2.4 s'],
      }),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });

    await pressCalculate();
    expect(screen.getByText(notice)).toBeInTheDocument();
    await tick();
    expect(screen.getByText(notice)).toBeInTheDocument();
    await tick();

    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(screen.getAllByText(notice)).toHaveLength(1);
    expect(screen.getByText('Planned 5 items in 2.4 s')).toBeInTheDocument();
  });
});

describe('Plan panel: Re-optimise a reused plan', () => {
  const REOPTIMISE = 'Re-optimise (ignore previous result)';

  it('offers Re-optimise on a reused plan, which calculates ignoring the previous result', async () => {
    const calls = stubPlanner({
      [`GET ${RUNS}`]: listed(['r2', 2, 'ready']),
      [`POST ${RUNS}?ignore_memo=true`]: ACCEPTED,
      [`GET ${JOB}`]: job('solving', { stoppable: true }),
      'GET /api/plan-runs/r2': readyRun('r2', 2, 'Briancon', null, {
        memo_hit: true,
        messages: ['Planned 5 items in 0.1 s', 'Reused the identical plan of run #1'],
      }),
    });
    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();
    expect(screen.getByText('Reused the identical plan of run #1')).toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: REOPTIMISE }));
    await settled();

    expect(count(calls, `POST ${RUNS}?ignore_memo=true`)).toBe(1);
    expect(count(calls, `POST ${RUNS}`)).toBe(0);
    await tick();
    expect(screen.getByRole('status')).toHaveTextContent('Solving');
  });

  it.each([
    ['a fresh run', { memo_hit: false, messages: ['Planned 5 items in 2.4 s'] }],
    ['a run stored before the messages', {}],
  ])('never offers Re-optimise on %s', async (_run, fields) => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      'GET /api/plan-runs/r1': readyRun('r1', 1, 'Briancon', null, fields),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: REOPTIMISE })).not.toBeInTheDocument();
  });
});

describe('Plan panel: provider header, objective and the engine messages', () => {
  const HEADER = 'Provider: Valhalla (map data 2026-11-01) / profile: 4x4';
  const UNREACHABLE = 'The road map service cannot be reached right now';
  const NOT_READY = 'The road map service is still loading its map';
  const OLD_RUN = readyRun('r1', 1, 'Briancon', TOTALS);

  it('shows the provider header above the itinerary and the objective label with the totals', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      'GET /api/plan-runs/r1': readyRun('r1', 1, 'Briancon', TOTALS, {
        provider_header: HEADER,
        objective: 'time',
        objective_label: 'Minimised road time',
      }),
    });

    render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    const header = screen.getByText(HEADER);
    const itinerary = screen.getByRole('list', { name: 'Itinerary' });
    expect(
      header.compareDocumentPosition(itinerary) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      within(screen.getByLabelText('Totals')).getByText('Minimised road time'),
    ).toBeInTheDocument();
  });

  it('shows a run stored before the header with neither line and no "undefined"', async () => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      'GET /api/plan-runs/r1': OLD_RUN,
    });

    const { container } = render(PlanPanel, { props: { projectId: 'p1' } });
    await settled();

    expect(screen.getByRole('list', { name: 'Itinerary' })).toBeInTheDocument();
    expect(container).not.toHaveTextContent('undefined');
    expect(container.querySelector('.provider, .objective')).toBeNull();
  });

  it.each([
    ['routing_engine_unreachable', UNREACHABLE],
    ['routing_engine_not_ready', NOT_READY],
  ])('shows the %s refusal as it is and keeps the last run on screen', async (code, message) => {
    stubPlanner({
      [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
      'GET /api/plan-runs/r1': OLD_RUN,
      [`POST ${RUNS}`]: { status: 503, body: { code, message } },
    });
    render(PlanPanel, { props: { projectId: 'p1' } });
    await pressCalculate();

    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(screen.getByText('Run 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeEnabled();
  });

  it.each([
    ['routing_engine_unreachable', UNREACHABLE],
    ['routing_engine_not_ready', NOT_READY],
  ])(
    'shows the message of a job that failed with %s and keeps the last run',
    async (reason, message) => {
      stubPlanner({
        [`GET ${RUNS}`]: listed(['r1', 1, 'ready']),
        'GET /api/plan-runs/r1': OLD_RUN,
        [`POST ${RUNS}`]: ACCEPTED,
        [`GET ${JOB}`]: job('failed', { reason, message }),
      });
      render(PlanPanel, { props: { projectId: 'p1' } });
      await pressCalculate();
      await tick();

      expect(screen.getByRole('alert')).toHaveTextContent(message);
      expect(screen.getByText('Run 1')).toBeInTheDocument();
    },
  );

  it.each([
    ['time', 'Best so far: 3h25', 12_300],
    ['distance', 'Best so far: 412.3 km', 412_300],
  ])('shows the best so far for %s as %s while solving', async (objective, line, value) => {
    stubPlanner({
      [`GET ${RUNS}`]: NO_RUNS,
      [`POST ${RUNS}`]: ACCEPTED,
      [`GET ${JOB}`]: job('solving', {
        incumbent: { unconfirmed_legs: 0, retraces: 0, objective: value, found_at_s: 2 },
      }),
    });
    render(PlanPanel, {
      props: { projectId: 'p1', objective: objective as 'time' | 'distance' },
    });

    await pressCalculate();
    await tick();

    expect(screen.getByText(line)).toBeInTheDocument();
  });
});
