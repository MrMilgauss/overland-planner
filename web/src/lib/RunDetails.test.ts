// The one closed Details of a ready run (D285): 'Plan run #N', the provider line, the objective, the planner's lines
// verbatim and in its order, and Re-optimise when the plan was reused. The web neither parses nor rewords a line (D211).
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); one example per rule of the component.
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RunDetails from './RunDetails.svelte';
import type { PlanRunDetail } from './api';

afterEach(cleanup);

const HEADER = 'Provider: Valhalla (map data 2026-11-18) / profile: 4x4';
const LINES = ['Planned 23 items in 0.3 s', 'Reused the identical plan of run #6'];
const REOPTIMISE = 'Re-optimise (ignore previous result)';

function run(fields: Record<string, unknown> = {}): PlanRunDetail {
  return {
    id: 'r7',
    project_id: 'p',
    number: 7,
    status: 'ready',
    failure_reason: null,
    stops: [],
    totals: null,
    report: null,
    estimate: false,
    provider_header: HEADER,
    objective: 'distance',
    objective_label: 'Minimised road distance',
    messages: LINES,
    memo_hit: true,
    ...fields,
  } as unknown as PlanRunDetail;
}

function details(): HTMLDetailsElement {
  return document.querySelector('details') as HTMLDetailsElement;
}

describe('RunDetails', () => {
  it('is one Details, closed, holding the five items in the planner order', () => {
    render(RunDetails, { props: { run: run(), onreoptimise: () => {} } });

    expect(document.querySelectorAll('details')).toHaveLength(1);
    expect(details().open).toBe(false);
    expect(within(details()).getByText('Details')).toBeInTheDocument();
    const inside = within(details());
    const shown = [
      inside.getByText('Plan run #7'),
      inside.getByText(HEADER),
      inside.getByText('Minimised road distance'),
      inside.getByText(LINES[0]),
      inside.getByText(LINES[1]),
      inside.getByRole('button', { name: REOPTIMISE, hidden: true }),
    ];
    shown.slice(1).forEach((item, at) => {
      expect(
        shown[at].compareDocumentPosition(item) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });
  });

  it('is closed again when another run is shown, whether or not Marco opened it', async () => {
    const { rerender } = render(RunDetails, { props: { run: run(), onreoptimise: () => {} } });
    await fireEvent.click(screen.getByText('Details'));
    expect(details().open).toBe(true);

    await rerender({ run: run({ id: 'r8', number: 8 }), onreoptimise: () => {} });

    expect(details().open).toBe(false);
    expect(screen.getByText('Plan run #8')).toBeInTheDocument();
  });

  it('offers Re-optimise only for a reused plan, and pressing it asks for a new plan', async () => {
    const reoptimise = vi.fn();
    const { rerender } = render(RunDetails, { props: { run: run(), onreoptimise: reoptimise } });
    await fireEvent.click(screen.getByRole('button', { name: REOPTIMISE, hidden: true }));
    expect(reoptimise).toHaveBeenCalledOnce();

    await rerender({ run: run({ memo_hit: false }), onreoptimise: reoptimise });
    expect(
      screen.queryByRole('button', { name: REOPTIMISE, hidden: true }),
    ).not.toBeInTheDocument();
  });

  it('shows a run stored before the lines with its number only, and no "undefined"', () => {
    const { container } = render(RunDetails, {
      props: {
        run: run({
          provider_header: undefined,
          objective_label: undefined,
          messages: undefined,
          memo_hit: undefined,
        }),
        onreoptimise: () => {},
      },
    });

    expect(screen.getByText('Plan run #7')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('undefined');
    expect(container.querySelectorAll('details p')).toHaveLength(1);
  });
});
