// The region search of the Road map screen (slice 12c, US-27): nothing is sent while typing, only on Search or Enter; it
// says what it fetches from Geofabrik; results show parent and size, mark the regions already covered, and Add hands the
// region to the page; the planner's refusals are shown. The fetch stub stands in for GET /api/road-map/catalogue.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); one test per behaviour.
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RegionSearch from './RegionSearch.svelte';

const UTAH = {
  key: 'us/utah',
  name: 'Utah',
  parent_name: 'United States of America',
  bytes: 1_100_000_000,
  in_map: false,
};
const ITALY = {
  key: 'italy',
  name: 'Italy',
  parent_name: 'Europe',
  bytes: 2_200_000_000,
  in_map: true,
};

function stub(reply: { status: number; body: unknown } | 'down') {
  const urls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      urls.push(url);
      if (reply === 'down') throw new TypeError('network');
      return new Response(JSON.stringify(reply.body), { status: reply.status });
    }),
  );
  return urls;
}

function open(chosen: string[] = []) {
  const add = vi.fn();
  render(RegionSearch, { chosen, add });
  return add;
}

const type = (words: string) =>
  fireEvent.input(screen.getByLabelText('Region name'), { target: { value: words } });
const search = () => fireEvent.click(screen.getByRole('button', { name: 'Search' }));

afterEach(() => vi.unstubAllGlobals());

describe('Region search', () => {
  it('sends nothing while typing and says what it fetches from Geofabrik', async () => {
    const urls = stub({ status: 200, body: { results: [] } });
    open();

    await type('Utah');

    expect(urls).toEqual([]);
    const form = screen.getByRole('form', { name: 'Search for a region' });
    expect(form).toHaveTextContent('Geofabrik');
    expect(form).toHaveTextContent('the size of the regions shown');
    expect(form).toHaveTextContent('the outline of a chosen one');
    expect(form).toHaveTextContent('no trip data');
  });

  it('searches on Search and on Enter and lists each region with its parent and size', async () => {
    const urls = stub({ status: 200, body: { results: [UTAH] } });
    open();
    await type('Utah');

    await search();
    expect(await screen.findByText('Utah, United States of America, 1.1 GB')).toBeVisible();
    await fireEvent.submit(screen.getByRole('form', { name: 'Search for a region' }));

    expect(urls[0]).toBe('/api/road-map/catalogue?q=Utah');
  });

  it('adds a result, and marks as covered a region the map has or the choice holds', async () => {
    stub({ status: 200, body: { results: [UTAH, ITALY] } });
    const add = open(['us/georgia']);
    await type('it');
    await search();

    await fireEvent.click(await screen.findByRole('button', { name: 'Add Utah' }));

    expect(add).toHaveBeenCalledWith(UTAH);
    expect(screen.queryByRole('button', { name: 'Add Italy' })).not.toBeInTheDocument();
    expect(screen.getByText('Already in the road map')).toBeVisible();
  });

  it('says so when nothing is found, and shows the planner’s refusal and a list that is down', async () => {
    stub({ status: 200, body: { results: [] } });
    open();
    await type('Zxqvbn');
    await search();
    expect(await screen.findByRole('status')).toHaveTextContent("No region found for 'Zxqvbn'");

    stub({ status: 422, body: { message: 'Type at least two letters' } });
    await type('U');
    await search();
    expect(await screen.findByRole('alert')).toHaveTextContent('Type at least two letters');
  });
});
