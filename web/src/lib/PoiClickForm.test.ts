// The small form that names a place clicked on the map (slice 09, step 10-05): Add hands the name on and closes only
// when the planner took it, an empty name stays open with the planner's own message, Cancel and Escape close it and
// add nothing. The planner is a stub of the `add` the map gives the form.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11).
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { PlannerError } from './api';
import PoiClickForm from './PoiClickForm.svelte';

function open(add = vi.fn(async (name: string) => void name)) {
  const close = vi.fn();
  render(PoiClickForm, { add, close });
  return { add, close };
}

describe('PoiClickForm', () => {
  it('adds the name typed, then closes', async () => {
    const { add, close } = open();
    await fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'Susa trailhead' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
    expect(add).toHaveBeenCalledExactlyOnceWith('Susa trailhead');
  });

  it("stays open with the planner's message when it refuses the name", async () => {
    const refusing = vi.fn(async () => {
      throw new PlannerError('A place needs a name', 422);
    });
    const { close } = open(refusing);
    await fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A place needs a name');
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
  });

  it('closes and adds nothing on Cancel and on Escape', async () => {
    const first = open();
    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(first.close).toHaveBeenCalledTimes(1);
    const second = open();
    await fireEvent.keyDown(screen.getAllByLabelText('Name')[1], { key: 'Escape' });
    expect(second.close).toHaveBeenCalledTimes(1);
    expect(first.add).not.toHaveBeenCalled();
    expect(second.add).not.toHaveBeenCalled();
  });
});
