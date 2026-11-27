// The progress of a running rebuild (slice 12c, US-30): which of the steps is done, which is on, which is to come, and from
// the building step the minutes left. The page gives the planner's own step and figures; the words come from roadMapView.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); the tick rule is a table in roadMapView.test.ts.
import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import RebuildProgress from './RebuildProgress.svelte';

const NOW = Date.parse('2026-11-27T20:17:00Z');

describe('Rebuild progress', () => {
  it('lists the steps, ticks the done ones and marks the one on', () => {
    render(RebuildProgress, {
      props: { step: 'downloading', stepsDone: 1, backAt: null, now: NOW },
    });

    const steps = screen.getByRole('region', { name: 'Rebuild progress' });
    expect(
      within(steps)
        .getAllByRole('listitem')
        .map((li) => li.textContent?.trim()),
    ).toEqual([
      'Waiting done',
      "Checking the Pi's disk and memory done",
      'Downloading',
      'Building',
      'Switching to the new map',
    ]);
    expect(within(steps).getByRole('listitem', { current: 'step' })).toHaveTextContent(
      'Downloading',
    );
    expect(steps).not.toHaveTextContent('left');
  });

  it('says Waiting is on while the helper has reported no step', () => {
    render(RebuildProgress, { props: { step: null, stepsDone: 0, backAt: null, now: NOW } });

    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Waiting');
  });

  it('says the minutes left from the building step', () => {
    render(RebuildProgress, {
      props: { step: 'building', stepsDone: 2, backAt: '2026-11-27T20:48:00Z', now: NOW },
    });

    expect(screen.getByRole('region', { name: 'Rebuild progress' })).toHaveTextContent(
      'about 31 minutes left',
    );
  });
});
