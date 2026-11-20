// The one Add control of Build the trip (D283): "Upload GPX trails", "Click on the map" and "Type coordinates" over the
// import and add-place calls, which the page gives it as `onupload` and `onplace`. A refusal of the planner is shown in
// its own words in the form.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); three menu entries, each one behaviour.
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import AddMenu from './AddMenu.svelte';
import { PlannerError } from './api';

function open(overrides: Record<string, unknown> = {}) {
  const props = {
    onupload: vi.fn(async () => {}),
    onplace: vi.fn(async () => {}),
    onclickmap: vi.fn(),
    ...overrides,
  };
  render(AddMenu, { props });
  return props;
}

const addButton = (): HTMLElement => screen.getByRole('button', { name: 'Add' });

async function chooseEntry(name: string): Promise<void> {
  await fireEvent.click(addButton());
  await fireEvent.click(screen.getByRole('menuitem', { name }));
}

describe('Add menu', () => {
  it('offers the three ways to add, only once opened', async () => {
    open();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    await fireEvent.click(addButton());

    expect(
      within(screen.getByRole('menu'))
        .getAllByRole('menuitem')
        .map((i) => i.textContent?.trim()),
    ).toEqual(['Upload GPX trails', 'Click on the map', 'Type coordinates']);
    expect(addButton()).toHaveAttribute('aria-expanded', 'true');
  });

  it('closes on Escape', async () => {
    open();
    await fireEvent.click(addButton());

    await fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('hands the GPX files chosen to the import', async () => {
    const { onupload } = open();
    const file = new File(['<gpx/>'], 'assietta.gpx', { type: 'application/gpx+xml' });

    await fireEvent.change(screen.getByLabelText('GPX files'), { target: { files: [file] } });

    await waitFor(() => expect(onupload).toHaveBeenCalledExactlyOnceWith([file]));
  });

  it('puts the map in its click mode and closes', async () => {
    const { onclickmap } = open();

    await chooseEntry('Click on the map');

    expect(onclickmap).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('adds the place typed with its decimal degrees, then closes the form', async () => {
    const { onplace } = open();
    await chooseEntry('Type coordinates');
    const form = screen.getByRole('form', { name: 'Type coordinates' });

    await fireEvent.input(within(form).getByLabelText('Name'), {
      target: { value: 'Lago del Moncenisio' },
    });
    await fireEvent.input(within(form).getByLabelText('Latitude'), {
      target: { value: '45.2280' },
    });
    await fireEvent.input(within(form).getByLabelText('Longitude'), {
      target: { value: '6.9420' },
    });
    await fireEvent.click(within(form).getByRole('button', { name: 'Add' }));

    await waitFor(() =>
      expect(onplace).toHaveBeenCalledExactlyOnceWith({
        name: 'Lago del Moncenisio',
        lat: 45.228,
        lon: 6.942,
      }),
    );
    await waitFor(() => expect(screen.queryByRole('form')).not.toBeInTheDocument());
  });

  it("keeps the form open with the planner's own refusal", async () => {
    open({
      onplace: vi.fn(async () => {
        throw new PlannerError('Latitude must be between -90 and 90', 422);
      }),
    });
    await chooseEntry('Type coordinates');
    const form = screen.getByRole('form', { name: 'Type coordinates' });

    await fireEvent.input(within(form).getByLabelText('Latitude'), { target: { value: '91' } });
    await fireEvent.click(within(form).getByRole('button', { name: 'Add' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent(
      'Latitude must be between -90 and 90',
    );
  });
});
