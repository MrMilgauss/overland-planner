// The trip's list (D283, D107 items): one list of places and trails with Start and End tags, a row menu on places only
// ("Set as start", "Set as end") and the pending-until-both rule for the anchors call, read-only while planning.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); the rule is a closed table of the cases of
// "which anchors are saved" x "which choices are made", so it is table-driven.
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import TripList from './TripList.svelte';
import type { Item } from './api';

function poi(name: string, overrides: Partial<Item> = {}): Item {
  return {
    id: name,
    type: 'poi',
    name,
    included: true,
    anchor: null,
    location: { lat: 45.0703, lon: 7.6869 },
    entry: null,
    exit: null,
    length_m: null,
    ...overrides,
  };
}

const assietta: Item = {
  id: 't1',
  type: 'track',
  name: "Strada dell'Assietta",
  included: false,
  anchor: null,
  location: null,
  entry: { lat: 45.056, lon: 7.041 },
  exit: { lat: 44.958, lon: 6.879 },
  length_m: 34_200,
};

function row(name: string): HTMLElement {
  const item = screen.getByText(name).closest('li');
  expect(item).not.toBeNull();
  return item as HTMLElement;
}

async function choose(place: string, choice: 'Set as start' | 'Set as end'): Promise<void> {
  await fireEvent.click(within(row(place)).getByRole('button', { name: `Actions for ${place}` }));
  await fireEvent.click(screen.getByRole('button', { name: choice }));
}

function tags(place: string): string[] {
  return ['Start', 'End', 'not saved yet'].filter((tag) =>
    within(row(place)).queryByText(tag, { exact: true }),
  );
}

describe('Trip list', () => {
  it("opens a place's actions as a disclosure and Escape closes it, back on its button", async () => {
    render(TripList, { props: { items: [poi('Briancon')], onanchors: async () => true } });
    const toggle = screen.getByRole('button', { name: 'Actions for Briancon' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const options = document.getElementById(toggle.getAttribute('aria-controls') ?? '')!;
    expect(
      within(options)
        .getAllByRole('button')
        .map((b) => b.textContent?.trim()),
    ).toEqual(['Set as start', 'Set as end']);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    within(options).getByRole('button', { name: 'Set as end' }).focus();

    await fireEvent.keyDown(window, { key: 'Escape' });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('lists every place and trail of the trip with its type', () => {
    render(TripList, { props: { items: [poi('Briancon'), assietta] } });

    const list = screen.getByRole('list', { name: 'Your trip' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(within(row('Briancon')).getByText('Place')).toBeInTheDocument();
    expect(within(row("Strada dell'Assietta")).getByText('Trail')).toBeInTheDocument();
  });

  it('says so when the trip has nothing yet', () => {
    render(TripList, { props: { items: [] } });

    expect(screen.getByText(/no trails or places yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it.each([
    ['start_end', ['Start', 'End']],
    ['start', ['Start']],
    ['end', ['End']],
    [null, []],
  ] as const)('tags a place saved as %s with %j', (anchor, expected) => {
    render(TripList, { props: { items: [poi('Torino', { anchor })] } });

    expect(tags('Torino')).toEqual(expected);
  });

  it('offers the row menu on places only, and neither Start nor End on a trail', () => {
    render(TripList, { props: { items: [poi('Torino'), assietta], onanchors: vi.fn() } });

    expect(within(row('Torino')).getByRole('button', { name: 'Actions for Torino' })).toBeVisible();
    expect(within(row("Strada dell'Assietta")).queryByRole('button')).not.toBeInTheDocument();
  });

  it('offers no menu at all while the trip is planned (read-only)', () => {
    render(TripList, { props: { items: [poi('Torino'), assietta], readonly: true } });

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  describe('the anchors call waits until both are chosen', () => {
    const A = 'Susa';
    const B = 'Briancon';
    const C = 'Aosta';
    type Choice = [string, 'Set as start' | 'Set as end'];
    // [saved, choices in order, the one anchors call expected (start, end) or none, tags of the first choice's place]
    const CASES: [string, Item[], Choice[], [string, string] | null, string[]][] = [
      [
        'start first, nothing saved',
        [poi(A), poi(B)],
        [[A, 'Set as start']],
        null,
        ['Start', 'not saved yet'],
      ],
      [
        'end first, nothing saved',
        [poi(A), poi(B)],
        [[B, 'Set as end']],
        null,
        ['End', 'not saved yet'],
      ],
      [
        'start then end',
        [poi(A), poi(B)],
        [
          [A, 'Set as start'],
          [B, 'Set as end'],
        ],
        [A, B],
        [],
      ],
      [
        'end then start',
        [poi(A), poi(B)],
        [
          [B, 'Set as end'],
          [A, 'Set as start'],
        ],
        [A, B],
        [],
      ],
      [
        'same place as start and end',
        [poi(A)],
        [
          [A, 'Set as start'],
          [A, 'Set as end'],
        ],
        [A, A],
        [],
      ],
      [
        'end with a start saved',
        [poi(A, { anchor: 'start' }), poi(B)],
        [[B, 'Set as end']],
        [A, B],
        [],
      ],
      [
        'a new start with both saved',
        [poi(A, { anchor: 'start' }), poi(B, { anchor: 'end' }), poi(C)],
        [[C, 'Set as start']],
        [C, B],
        [],
      ],
      [
        'a new end with start_end saved',
        [poi(A, { anchor: 'start_end' }), poi(B)],
        [[B, 'Set as end']],
        [A, B],
        [],
      ],
    ];

    it.each(CASES)('%s', async (_name, items, choices, call, firstTags) => {
      const onanchors = vi.fn(async () => true);
      render(TripList, { props: { items, onanchors } });

      for (const [place, choice] of choices) await choose(place, choice);

      if (call) await waitFor(() => expect(onanchors).toHaveBeenCalledExactlyOnceWith(...call));
      else {
        expect(onanchors).not.toHaveBeenCalled();
        expect(tags(choices[0][0])).toEqual(firstTags);
      }
    });

    it('keeps the choice, still not saved, when the planner refuses it', async () => {
      const onanchors = vi.fn(async () => false);
      render(TripList, { props: { items: [poi(A), poi(B)], onanchors } });

      await choose(A, 'Set as start');
      await choose(B, 'Set as end');

      await waitFor(() => expect(onanchors).toHaveBeenCalledTimes(1));
      expect(tags(A)).toEqual(['Start', 'not saved yet']);
      expect(tags(B)).toEqual(['End', 'not saved yet']);
    });
  });

  it('tags an item that is left out of the plan with a muted "Left out", and no included row', () => {
    render(TripList, {
      props: { items: [assietta, poi('Casa Marco, Torino'), poi('Rifugio', { included: false })] },
    });

    expect(within(row("Strada dell'Assietta")).getByText('Left out')).toBeInTheDocument();
    expect(within(row('Rifugio')).getByText('Left out')).toBeInTheDocument();
    expect(within(row('Casa Marco, Torino')).queryByText('Left out')).not.toBeInTheDocument();
  });
});
