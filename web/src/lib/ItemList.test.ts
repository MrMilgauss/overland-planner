// Item list of the workspace (D107 items): type, name, Included and the S/E, Start or End badge.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); anchor assignment is property-tested at
// the domain level (step 03-09), the badge mapping here is a closed set of four cases, parametrized.
import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ItemList from './ItemList.svelte';
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

describe('Item list', () => {
  it('shows every item with its type and whether it is Included', () => {
    render(ItemList, { props: { items: [poi('Briancon'), assietta] } });

    const list = screen.getByRole('list', { name: 'Items' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(within(row('Briancon')).getByText('POI')).toBeInTheDocument();
    expect(within(row('Briancon')).getByText('Included')).toBeInTheDocument();
    expect(within(row("Strada dell'Assietta")).getByText('track')).toBeInTheDocument();
    expect(within(row("Strada dell'Assietta")).queryByText('Included')).not.toBeInTheDocument();
  });

  it.each([
    ['start_end', 'S/E'],
    ['start', 'Start'],
    ['end', 'End'],
  ] as const)('shows the %s anchor as the %s badge', (anchor, badge) => {
    render(ItemList, { props: { items: [poi('Casa Marco, Torino', { anchor }), poi('Aosta')] } });

    expect(within(row('Casa Marco, Torino')).getByText(badge)).toBeInTheDocument();
    for (const other of ['S/E', 'Start', 'End']) {
      expect(within(row('Aosta')).queryByText(other)).not.toBeInTheDocument();
    }
  });

  it('says so when the project has no items yet', () => {
    render(ItemList, { props: { items: [] } });

    expect(screen.getByText(/no trails or places yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });
});
