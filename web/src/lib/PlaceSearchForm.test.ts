// The place search form of the Add menu (slice 12c, US-29): nothing is sent while typing, only on Search or Enter; a
// press twice sends one search; up to five results each with Add (the add-place call, the form stays open); the two
// errors. The fetch stub stands in for GET /api/places/search (the port of the form).
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); one test per behaviour.
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PlaceSearchForm from './PlaceSearchForm.svelte';

const VERDON = {
  name: 'Gorges du Verdon',
  region: "Provence-Alpes-Côte d'Azur",
  country: 'France',
  lat: 43.7686,
  lon: 6.3322,
};

function stubSearch(reply: { status: number; body: unknown } | 'down') {
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

function open(add = vi.fn(async () => {})) {
  const close = vi.fn();
  render(PlaceSearchForm, { add, close });
  return { add, close };
}

const input = (): HTMLElement => screen.getByLabelText('Place name');
const searchButton = (): HTMLElement => screen.getByRole('button', { name: 'Search' });

async function type(words: string): Promise<void> {
  await fireEvent.input(input(), { target: { value: words } });
}

afterEach(() => vi.unstubAllGlobals());

describe('Place search form', () => {
  it('sends nothing while typing and says what leaves the house', async () => {
    const urls = stubSearch({ status: 200, body: [] });
    open();

    await type('Gorges du Verdon');

    expect(urls).toEqual([]);
    expect(screen.getByRole('form', { name: 'Search for a place' })).toHaveTextContent(
      "Only the words you type are sent, from your home connection, to OpenStreetMap's public place search (Nominatim). Your trip and files stay at home. Don't type personal details. Search © OpenStreetMap contributors.",
    );
  });

  it('searches on the Search button and on Enter, one search each, and lists the results with their region', async () => {
    const urls = stubSearch({ status: 200, body: [VERDON] });
    open();
    await type('Gorges du Verdon');

    await fireEvent.click(searchButton());

    expect(
      await screen.findByText("Gorges du Verdon, Provence-Alpes-Côte d'Azur, France"),
    ).toBeVisible();
    expect(urls).toEqual(['/api/places/search?q=Gorges%20du%20Verdon']);

    await type('Lagos');
    await fireEvent.submit(screen.getByRole('form', { name: 'Search for a place' }));
    await waitFor(() => expect(urls).toHaveLength(2));
  });

  it('sends one search when Search is pressed twice quickly', async () => {
    const urls = stubSearch({ status: 200, body: [VERDON] });
    open();
    await type('Gorges du Verdon');

    await fireEvent.click(searchButton());
    await fireEvent.click(searchButton());

    await screen.findByRole('list', { name: 'Search results' });
    expect(urls).toHaveLength(1);
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('shows five results at most, each with Add that adds the place and keeps the form open', async () => {
    const six = Array.from({ length: 6 }, (_, i) => ({
      ...VERDON,
      name: `Verdon ${i}`,
      lat: 43 + i,
    }));
    stubSearch({ status: 200, body: six });
    const { add, close } = open();
    await type('Verdon');
    await fireEvent.click(searchButton());
    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(5);

    await fireEvent.click(within(rows[1]).getByRole('button', { name: 'Add' }));

    await waitFor(() =>
      expect(add).toHaveBeenCalledExactlyOnceWith({ name: 'Verdon 1', lat: 44, lon: 6.3322 }),
    );
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole('form', { name: 'Search for a place' })).toBeVisible();
  });

  it('says no place was found, with a hint to add it on the map', async () => {
    stubSearch({ status: 200, body: [] });
    open();
    await type('Zxqvbn');
    await fireEvent.click(searchButton());

    expect(await screen.findByRole('status')).toHaveTextContent(
      "No place found for 'Zxqvbn'. Try another spelling or add it by clicking on the map.",
    );
  });

  it.each([
    [
      'busy',
      {
        status: 503,
        body: {
          code: 'place_search_unavailable',
          message: 'Place search is not available right now',
        },
      },
    ],
    ['unreachable', 'down' as const],
  ])('says the place search is not answering when it is %s', async (_case, reply) => {
    stubSearch(reply);
    open();
    await type('Gorges du Verdon');
    await fireEvent.click(searchButton());

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "The place search isn't answering. Try again in a minute, or add the place another way.",
    );
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  it("shows the planner's own refusal of a name too short", async () => {
    stubSearch({
      status: 422,
      body: { code: 'validation_error', message: 'Type at least two letters' },
    });
    open();
    await type('a');
    await fireEvent.click(searchButton());

    expect(await screen.findByRole('alert')).toHaveTextContent('Type at least two letters');
  });

  it('closes on Close', async () => {
    const { close } = open();

    await fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(close).toHaveBeenCalledTimes(1);
  });
});
