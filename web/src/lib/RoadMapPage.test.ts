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
const LIMITS = { max_gb: 8, max_bytes: 8_000_000_000, next_rebuild_from: null };
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
) {
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined });
      if (url === '/api/road-map')
        return new Response(
          JSON.stringify({ served, limits: LIMITS, server_utc_offset_minutes: 60 }),
        );
      if (url.startsWith('/api/road-map/catalogue'))
        return new Response(JSON.stringify({ results: [UTAH] }));
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
});
