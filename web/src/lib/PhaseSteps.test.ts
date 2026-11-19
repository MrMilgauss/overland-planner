// The three phase steps (D283): their order, the current one marked, and 'Your route' as the way back to a ready result.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); one example per phase.
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PhaseSteps from './PhaseSteps.svelte';
import type { TripPhase } from './tripPhase';

afterEach(cleanup);

const NAMES = ['Build the trip', 'Planning', 'Your route'];

describe('PhaseSteps', () => {
  it.each<[TripPhase, string]>([
    ['build', 'Build the trip'],
    ['planning', 'Planning'],
    ['route', 'Your route'],
  ])('lists the three steps in order and marks %s as the current one', (phase, current) => {
    render(PhaseSteps, { props: { phase, canShowRoute: false, onshowroute: () => {} } });

    const steps = screen.getAllByRole('listitem');
    expect(steps.map((step) => step.textContent?.replace(/^\d\s*/, '').trim())).toEqual(NAMES);
    const marked = steps.filter(
      (step) =>
        step.querySelector('[aria-current="step"]') || step.getAttribute('aria-current') === 'step',
    );
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveTextContent(current);
  });

  it('makes Your route a button back to the result only when a ready route exists', async () => {
    const back = vi.fn();
    const { rerender } = render(PhaseSteps, {
      props: { phase: 'build', canShowRoute: false, onshowroute: back },
    });
    expect(screen.queryByRole('button', { name: 'Your route' })).not.toBeInTheDocument();

    await rerender({ phase: 'build', canShowRoute: true, onshowroute: back });
    await fireEvent.click(screen.getByRole('button', { name: 'Your route' }));
    expect(back).toHaveBeenCalledOnce();
  });
});
