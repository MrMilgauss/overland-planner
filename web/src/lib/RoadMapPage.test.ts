// The Road map screen (slice 12c, US-27): the served regions with sizes, the total and the map date, or "Map coverage
// unknown"; a region found by name is added, and a loaded one removed, as a pending change that never alters the
// served list; the preview of the pending choice says when a region is not linked by land. The fetch stub stands in for
// the planner (GET /api/road-map, GET /api/road-map/catalogue, POST /api/road-map/change/preview).
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); one test per behaviour.
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RoadMapPage from './RoadMapPage.svelte';

const region = (key: string, name: string, bytes: number) => ({
  key,
  name,
  parent_name: 'Europe',
  bytes,
});
const SERVED = {
  known: true,
  map_date: '2026-11-27T12:00:00Z',
  regions: [region('italy', 'Italy', 2_200_000_000), region('austria', 'Austria', 700_000_000)],
  total_bytes: 2_900_000_000,
};
const UTAH = {
  key: 'us/utah',
  name: 'Utah',
  parent_name: 'United States of America',
  bytes: 1_100_000_000,
  in_map: false,
};
const LIMITS = {
  max_gb: 8,
  max_bytes: 8_000_000_000,
  next_rebuild_from: null,
  changes_available: true,
  rebuilds_set_up: true,
  helper_seen_at: '2026-11-27T12:00:00Z',
};
const NO_CHANGE = { state: 'none', start_at: null, added: [], removed: [] };
const PLANNED = {
  state: 'planned',
  start_at: null,
  added: [{ key: 'us/utah', name: 'Utah' }],
  removed: [],
};
type Answer = { status: number; body?: unknown };
interface World {
  change?: unknown;
  limits?: unknown;
  posted?: Answer;
  cancelled?: Answer;
  back?: string | null;
  readFails?: boolean;
}
const RUNNING_AT = (step: string | null, stepsDone: number, back: string | null) => ({
  state: 'running',
  step,
  steps_done: stepsDone,
  start_at: null,
  added: [{ key: 'us/utah', name: 'Utah' }],
  removed: [],
  back,
});
const SUMMARY = {
  added: [{ key: 'us/utah', name: 'Utah' }],
  removed: [],
  total_bytes: 4_000_000_000,
  estimate: { total_minutes: 35, pause_minutes: 24 },
  land_groups: [],
};
const NOTE = 'Utah is not linked by land to your other regions. Trips inside Utah are fine.';

function plan(
  served: unknown,
  preview: { status: number; body: unknown } = {
    status: 200,
    body: { ...SUMMARY, not_linked_note: null },
  },
  world: World = {},
) {
  const calls: { url: string; method?: string; body?: string }[] = [];
  world.change ??= NO_CHANGE;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method, body: init?.body as string | undefined });
      if (url === '/api/road-map' && world.readFails) return new Response('{}', { status: 503 });
      if (url === '/api/road-map')
        return new Response(
          JSON.stringify({
            served,
            change: world.change,
            limits: world.limits ?? LIMITS,
            server_utc_offset_minutes: 60,
            planning_paused: world.back !== undefined && world.back !== null,
            planning_back_at: world.back ?? null,
          }),
        );
      if (url.startsWith('/api/road-map/catalogue'))
        return new Response(JSON.stringify({ results: [UTAH] }));
      if (url === '/api/road-map/change' && init?.method === 'DELETE') {
        const answer = world.cancelled ?? { status: 204 };
        if (answer.status === 204) world.change = NO_CHANGE;
        return new Response(answer.status === 204 ? null : JSON.stringify(answer.body), {
          status: answer.status,
        });
      }
      if (url === '/api/road-map/change') {
        const answer = world.posted ?? { status: 201, body: { ...SUMMARY, not_linked_note: null } };
        if (answer.status === 201) world.change = PLANNED;
        return new Response(JSON.stringify(answer.body), { status: answer.status });
      }
      return new Response(JSON.stringify(preview.body), { status: preview.status });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const loaded = () => screen.findByRole('list', { name: 'Loaded regions' });

describe('Road map page', () => {
  it('shows the served regions with parent and size, the total and the map date', async () => {
    plan(SERVED);
    render(RoadMapPage);

    const list = await loaded();

    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(within(list).getByText('Italy, Europe, 2.2 GB')).toBeVisible();
    expect(screen.getByText('Total: 2.9 GB')).toBeVisible();
    expect(screen.getByText('Map data: 27 November 2026')).toBeVisible();
  });

  it('says the regions are unknown, keeps the date, lists nothing and offers the refresh', async () => {
    plan({ known: false, map_date: '2026-11-26T12:00:00Z', regions: [], total_bytes: 0 });
    render(RoadMapPage);

    expect(await screen.findByText('Map coverage unknown')).toBeVisible();

    expect(screen.getByText('Map data: 26 November 2026')).toBeVisible();
    expect(screen.queryByRole('list', { name: 'Loaded regions' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh map data' })).toBeVisible();
  });

  it('removes a loaded region as a pending change that keeps it listed, and undoes it', async () => {
    const calls = plan(SERVED);
    render(RoadMapPage);
    const list = await loaded();

    await fireEvent.click(within(list).getByRole('button', { name: 'Remove Austria' }));

    const row = within(list)
      .getByText(/Austria/)
      .closest('li')!;
    expect(row).toHaveTextContent('to be removed');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    await vi.waitFor(() =>
      expect(JSON.parse(calls.at(-1)!.body!)).toEqual({ region_keys: ['italy'] }),
    );

    await fireEvent.click(within(row).getByRole('button', { name: 'Keep Austria' }));
    expect(row).not.toHaveTextContent('to be removed');
  });

  it('adds a found region as a pending one, leaves the loaded list alone and says it is not linked by land', async () => {
    const calls = plan(SERVED, { status: 200, body: { ...SUMMARY, not_linked_note: NOTE } });
    render(RoadMapPage);
    const list = await loaded();
    await fireEvent.input(screen.getByLabelText('Region name'), { target: { value: 'Utah' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await fireEvent.click(await screen.findByRole('button', { name: 'Add Utah' }));

    const pending = screen.getByRole('list', { name: 'Pending changes' });
    expect(pending).toHaveTextContent('Utah');
    expect(pending).toHaveTextContent('to be added');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(await screen.findByRole('status')).toHaveTextContent(NOTE);
    expect(JSON.parse(calls.at(-1)!.body!)).toEqual({
      region_keys: ['italy', 'austria', 'us/utah'],
    });

    await fireEvent.click(within(pending).getByRole('button', { name: "Don't add Utah" }));
    expect(screen.queryByRole('list', { name: 'Pending changes' })).not.toBeInTheDocument();
  });

  it('shows the planner’s refusal of a pending choice', async () => {
    plan(SERVED, {
      status: 422,
      body: { message: "Utah is already in the road map as part of 'United States'" },
    });
    render(RoadMapPage);
    await fireEvent.click(within(await loaded()).getByRole('button', { name: 'Remove Austria' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Utah is already in the road map');
  });

  it('says the road map could not be read', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 500 })),
    );
    render(RoadMapPage);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not read the road map.');
  });

  it('shows the size and time of the pending choice', async () => {
    plan(SERVED, { status: 200, body: { ...SUMMARY, not_linked_note: null } });
    render(RoadMapPage);
    await fireEvent.input(await screen.findByLabelText('Region name'), {
      target: { value: 'Utah' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await fireEvent.click(await screen.findByRole('button', { name: 'Add Utah' }));

    expect(await screen.findByText('Total download 4.0 GB')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Rebuild road map' })).toBeVisible();
  });

  it('refuses, in words, an addition above the limit and leaves the pending choice as it was', async () => {
    plan(SERVED, { status: 200, body: { ...SUMMARY, total_bytes: 9_000_000_000 } });
    render(RoadMapPage);
    await fireEvent.input(await screen.findByLabelText('Region name'), {
      target: { value: 'Utah' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await fireEvent.click(await screen.findByRole('button', { name: 'Add Utah' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The download would be 9.0 GB and the limit is 8 GB.',
    );
    expect(screen.queryByRole('list', { name: 'Pending changes' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rebuild road map' })).not.toBeInTheDocument();
  });

  it.each([
    ['none', { ...NO_CHANGE }, []],
    ['cancelled', { ...NO_CHANGE, state: 'cancelled' }, []],
    ['planned now', { ...PLANNED }, ['Waiting to start within a minute', 'Cancel']],
    [
      'planned later',
      { ...PLANNED, start_at: '2030-12-02T01:00:00Z' },
      ['Rebuild planned for', 'Cancel'],
    ],
    ['running', { ...PLANNED, state: 'running' }, ['The rebuild has started']],
  ])('tells a %s change', async (_state, change, words) => {
    plan(SERVED, undefined, { change });
    render(RoadMapPage);
    await loaded();

    const section = screen.queryByRole('region', { name: 'Planned rebuild' });

    if (words.length === 0) expect(section).not.toBeInTheDocument();
    for (const word of words) expect(section).toHaveTextContent(word);
    expect(!!screen.queryByRole('button', { name: 'Cancel' })).toBe(words.includes('Cancel'));
  });

  it.each([
    [{ ...LIMITS, rebuilds_set_up: false }, "Rebuilds aren't set up on the Pi yet"],
    [{ ...LIMITS, changes_available: false }, "Changing the road map isn't available right now"],
  ])('says changes are not possible and offers none (%#)', async (limits, words) => {
    plan(SERVED, undefined, { limits });
    render(RoadMapPage);
    const list = await loaded();

    expect(screen.getByText(words)).toBeVisible();
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(
      screen.queryByRole('button', { name: /Remove|Refresh map data/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Region name')).not.toBeInTheDocument();
  });

  it('cancels a planned change and shows the served map as before', async () => {
    const calls = plan(SERVED, undefined, { change: PLANNED });
    render(RoadMapPage);
    await loaded();

    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await vi.waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Planned rebuild' })).not.toBeInTheDocument(),
    );
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
    expect(screen.getByText('Total: 2.9 GB')).toBeVisible();
  });

  it('says in the planner’s words that a started change cannot be cancelled, and keeps it', async () => {
    plan(SERVED, undefined, {
      change: PLANNED,
      cancelled: { status: 409, body: { message: 'The rebuild has already started' } },
    });
    render(RoadMapPage);
    await loaded();

    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The rebuild has already started');
    expect(screen.getByRole('region', { name: 'Planned rebuild' })).toBeVisible();
  });

  it('sends the chosen regions and the start time as UTC, then shows the plan', async () => {
    const calls = plan(SERVED);
    render(RoadMapPage);
    await fireEvent.click(within(await loaded()).getByRole('button', { name: 'Remove Austria' }));
    await fireEvent.click(await screen.findByRole('radio', { name: 'Start at a time' }));
    await fireEvent.input(screen.getByLabelText('Start time'), {
      target: { value: '2030-12-02T02:00' },
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Rebuild road map' }));

    const sent = await vi.waitFor(() => {
      const post = calls.find((c) => c.url === '/api/road-map/change' && c.method === 'POST');
      expect(post).toBeDefined();
      return JSON.parse(post!.body!);
    });
    expect(sent).toEqual({
      region_keys: ['italy'],
      start_at: new Date('2030-12-02T02:00').toISOString(),
    });
    expect(await screen.findByRole('region', { name: 'Planned rebuild' })).toBeVisible();
  });

  it('does not offer the rebuild when the pending choice would leave no region', async () => {
    plan(SERVED);
    render(RoadMapPage);
    await fireEvent.click(within(await loaded()).getByRole('button', { name: 'Remove Austria' }));
    expect(await screen.findByRole('button', { name: 'Rebuild road map' })).toBeEnabled();

    await fireEvent.click(within(await loaded()).getByRole('button', { name: 'Remove Italy' }));

    expect(screen.getByRole('button', { name: 'Rebuild road map' })).toBeDisabled();
  });

  it('refreshes the map data as the same workflow: same regions asked, same summary, no region list sent', async () => {
    const calls = plan(SERVED, {
      status: 200,
      body: { ...SUMMARY, added: [], total_bytes: 2_900_000_000 },
    });
    render(RoadMapPage);
    await loaded();

    await fireEvent.click(screen.getByRole('button', { name: 'Refresh map data' }));

    expect(await screen.findByText('Total download 2.9 GB')).toBeVisible();
    expect(screen.getByRole('radio', { name: 'Rebuild now' })).toBeVisible();
    await fireEvent.click(screen.getByRole('button', { name: 'Rebuild road map' }));
    await vi.waitFor(() =>
      expect(
        calls.find((c) => c.url === '/api/road-map/change' && c.method === 'POST'),
      ).toBeDefined(),
    );
    expect(
      JSON.parse(calls.find((c) => c.url === '/api/road-map/change' && c.method === 'POST')!.body!),
    ).toEqual({});
  });

  it('shows the planner’s refusal of a second change in its words', async () => {
    plan(SERVED, undefined, {
      change: PLANNED,
      posted: {
        status: 409,
        body: { message: 'A change is already planned: apply or cancel it first' },
      },
    });
    render(RoadMapPage);
    await fireEvent.click(within(await loaded()).getByRole('button', { name: 'Remove Austria' }));

    await fireEvent.click(await screen.findByRole('button', { name: 'Rebuild road map' }));

    expect(await screen.findByText(/A change is already planned/)).toBeVisible();
  });

  it('shows the step a running rebuild is in, with the time left from the building step', async () => {
    plan(SERVED, undefined, {
      change: RUNNING_AT('building', 2, null),
      back: new Date(Date.now() + 31 * 60_000).toISOString(),
    });
    render(RoadMapPage);
    await loaded();

    const steps = screen.getByRole('region', { name: 'Rebuild progress' });
    expect(within(steps).getByRole('listitem', { current: 'step' })).toHaveTextContent('Building');
    expect(steps).toHaveTextContent(/about 3[01] minutes left/);
    expect(screen.getByText('The rebuild has started')).toBeVisible();
  });

  it('shows no progress for a change that is only planned', async () => {
    plan(SERVED, undefined, { change: PLANNED });
    render(RoadMapPage);
    await loaded();

    expect(screen.queryByRole('region', { name: 'Rebuild progress' })).not.toBeInTheDocument();
  });

  describe('asking the planner again', () => {
    const readsOf = (calls: { url: string; method?: string }[]) =>
      calls.filter((call) => call.url === '/api/road-map' && call.method === undefined).length;

    afterEach(() => vi.useRealTimers());

    it('every 10 seconds while a change is running, and moves the step on', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const world: World = { change: RUNNING_AT('downloading', 1, null) };
      const calls = plan(SERVED, undefined, world);
      render(RoadMapPage);
      await vi.advanceTimersByTimeAsync(0);
      expect(readsOf(calls)).toBe(1);

      await vi.advanceTimersByTimeAsync(9_999);
      expect(readsOf(calls)).toBe(1);
      world.change = RUNNING_AT('building', 2, null);
      await vi.advanceTimersByTimeAsync(1);
      expect(readsOf(calls)).toBe(2);
      await vi.advanceTimersByTimeAsync(0);
      expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Building');
      await vi.advanceTimersByTimeAsync(10_000);
      expect(readsOf(calls)).toBe(3);
    });

    it('every 10 seconds while a change is planned', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const calls = plan(SERVED, undefined, { change: PLANNED });
      render(RoadMapPage);
      await vi.advanceTimersByTimeAsync(10_000);
      expect(readsOf(calls)).toBe(2);
    });

    it('once on open, and no more, when no change is waiting or running', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const calls = plan(SERVED);
      render(RoadMapPage);
      await vi.advanceTimersByTimeAsync(60_000);
      expect(readsOf(calls)).toBe(1);
    });

    it('stops when the change ends', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const world: World = { change: RUNNING_AT('switching', 3, null) };
      const calls = plan(SERVED, undefined, world);
      render(RoadMapPage);
      await vi.advanceTimersByTimeAsync(0);
      world.change = NO_CHANGE;
      await vi.advanceTimersByTimeAsync(10_000);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(readsOf(calls)).toBe(2);
    });

    it('goes on every 10 seconds after a failed read while a change runs, and clears the alert when one succeeds', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const world: World = { change: RUNNING_AT('downloading', 1, null) };
      const calls = plan(SERVED, undefined, world);
      render(RoadMapPage);
      await vi.advanceTimersByTimeAsync(0);

      world.readFails = true;
      await vi.advanceTimersByTimeAsync(10_000);
      expect(screen.getByRole('alert')).toBeVisible();
      world.readFails = false;
      await vi.advanceTimersByTimeAsync(10_000);

      expect(readsOf(calls)).toBe(3);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('stops when the page is left', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const calls = plan(SERVED, undefined, { change: RUNNING_AT('building', 2, null) });
      const { unmount } = render(RoadMapPage);
      await vi.advanceTimersByTimeAsync(0);
      unmount();
      await vi.advanceTimersByTimeAsync(30_000);
      expect(readsOf(calls)).toBe(1);
    });
  });

  it('reads an answer without a change as no change', async () => {
    plan(SERVED, undefined, { change: undefined });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ served: SERVED, limits: LIMITS }))),
    );
    render(RoadMapPage);
    await loaded();

    expect(screen.queryByRole('region', { name: 'Planned rebuild' })).not.toBeInTheDocument();
  });

  describe('the result of a rebuild', () => {
    const DISK =
      "The rebuild didn't finish: the Pi has 18 GB of free disk and needs 25 GB. The previous road map is back (map data 27 November 2026); nothing is lost. Your change is kept: free some space and press Rebuild road map again.";
    const result = (code: string | null, message: string) => ({
      code,
      message,
      finished_at: '2026-11-28T01:56:00Z',
    });
    const result_of = () => screen.findByRole('region', { name: 'Rebuild result' });

    it('says a rebuild is done in the planner’s words, beside the regions and date now served', async () => {
      const message =
        'Road map rebuilt on 28 November at 02:56. Utah added; 3 regions, map data 28 November 2026.';
      plan(
        {
          ...SERVED,
          map_date: '2026-11-28T01:00:00Z',
          regions: [...SERVED.regions, region('us/utah', 'Utah', 1_100_000_000)],
        },
        undefined,
        {
          change: {
            state: 'done',
            start_at: null,
            added: [],
            removed: [],
            result: result(null, message),
          },
        },
      );
      render(RoadMapPage);

      expect(await result_of()).toHaveTextContent(message);
      expect(within(await loaded()).getByText('Utah, Europe, 1.1 GB')).toBeVisible();
      expect(screen.getByText('Map data: 28 November 2026')).toBeVisible();
      expect(screen.queryByRole('region', { name: 'Planned rebuild' })).not.toBeInTheDocument();
    });

    it('says why a rebuild failed word for word, keeps the old map, and offers to rebuild the kept change again', async () => {
      const calls = plan(SERVED, undefined, {
        change: {
          state: 'failed',
          start_at: null,
          added: [{ key: 'us/utah', name: 'Utah' }],
          removed: [],
          result: result('disk', DISK),
        },
      });
      render(RoadMapPage);

      expect(await result_of()).toHaveTextContent(DISK);
      expect(screen.getByRole('alert')).toHaveTextContent(DISK);
      expect(screen.queryByText(/\bdisk\b$/)).not.toBeInTheDocument();
      expect(within(await loaded()).getAllByRole('listitem')).toHaveLength(2);
      expect(screen.getByText('Map data: 27 November 2026')).toBeVisible();
      const pending = await screen.findByRole('list', { name: 'Pending changes' });
      expect(within(pending).getByText(/Utah/)).toBeVisible();
      await fireEvent.click(await screen.findByRole('button', { name: 'Rebuild road map' }));
      const sent = calls.find((c) => c.url === '/api/road-map/change' && c.method === 'POST');
      expect(JSON.parse(sent?.body ?? '{}').region_keys).toEqual(['italy', 'austria', 'us/utah']);
    });

    it('shows nothing of a cancelled change', async () => {
      plan(SERVED, undefined, {
        change: {
          state: 'cancelled',
          start_at: null,
          added: [],
          removed: [],
          result: result(null, 'x'),
        },
      });
      render(RoadMapPage);
      await loaded();

      expect(screen.queryByRole('region', { name: 'Rebuild result' })).not.toBeInTheDocument();
    });
  });
});
