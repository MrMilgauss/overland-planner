// The summary of a pending road-map change (slice 12c, US-27 S5 and US-31 S1, S2, S5): what is added and removed, the
// size, the estimate with the part without planning, the not-linked note, the choice of now or a start time, or the
// refusal of the day. The component is shown what the planner answered and says it; the plan is sent by the page.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); one test per behaviour.
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ChangePreview, RoadMapLimits } from './api';
import ChangeSummary from './ChangeSummary.svelte';

const SUMMARY: ChangePreview = {
  added: [{ key: 'portugal', name: 'Portugal' }],
  removed: [{ key: 'austria', name: 'Austria' }],
  total_bytes: 6_800_000_000,
  estimate: { total_minutes: 58, pause_minutes: 41 },
  not_linked_note: null,
};
const LIMITS: RoadMapLimits = { max_gb: 8, max_bytes: 8_000_000_000, next_rebuild_from: null };

function show(overrides: Partial<ChangePreview> = {}, limits = LIMITS, offset = 60) {
  const choose = vi.fn();
  render(ChangeSummary, {
    summary: { ...SUMMARY, ...overrides },
    limits,
    serverOffsetMinutes: offset,
    choose,
  });
  return choose;
}

const zone = process.env.TZ;
afterEach(() => {
  if (zone === undefined) delete process.env.TZ;
  else process.env.TZ = zone;
});

describe('Change summary', () => {
  it('says what is added and removed, the size and the estimate, and offers the rebuild', () => {
    show();

    expect(screen.getByText('Adds Portugal')).toBeVisible();
    expect(screen.getByText('Removes Austria')).toBeVisible();
    expect(screen.getByText('Total download 6.8 GB')).toBeVisible();
    expect(
      screen.getByText(
        'Estimate: about 58 minutes in all, of which about 41 without planning (planning is paused).',
      ),
    ).toBeVisible();
    expect(screen.getByRole('button', { name: 'Rebuild road map' })).toBeEnabled();
  });

  it('adds the note of a region far from the others as information and keeps the rebuild offered', () => {
    show({ not_linked_note: 'Utah is not linked by land to your other regions.' });

    expect(screen.getByRole('status')).toHaveTextContent('Utah is not linked by land');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rebuild road map' })).toBeVisible();
  });

  it('offers now, chosen, or a start time that appears and is handed over as UTC', async () => {
    process.env.TZ = 'Europe/Rome';
    const choose = show({}, LIMITS, 0);
    expect(screen.getByRole('radio', { name: 'Rebuild now' })).toBeChecked();
    expect(screen.queryByLabelText('Start time')).not.toBeInTheDocument();

    await fireEvent.click(screen.getByRole('radio', { name: 'Start at a time' }));
    await fireEvent.input(screen.getByLabelText('Start time'), {
      target: { value: '2030-12-02T02:00' },
    });

    expect(choose).toHaveBeenLastCalledWith('2030-12-02T01:00:00.000Z');
    expect(screen.getByText('Rebuild at 02:00 on 2 December (Pi time)')).toBeVisible();

    await fireEvent.click(screen.getByRole('radio', { name: 'Rebuild now' }));
    expect(choose).toHaveBeenLastCalledWith(null);
  });

  it('refuses the day when a map is already kept, with the next time in local time, and offers no rebuild', () => {
    process.env.TZ = 'Europe/Rome';
    show({}, { ...LIMITS, next_rebuild_from: '2026-11-28T00:00:00Z' }, 60);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'The next rebuild can start from 01:00 on 28 November.',
    );
    expect(screen.queryByRole('button', { name: 'Rebuild road map' })).not.toBeInTheDocument();
  });
});
