// The first route card (D286): status, whether the roads are real, Export GPX and Edit trip; the older route under
// Couldn't plan is headed 'Previous route' and keeps its export (D208).
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); one example per card variant.
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RouteCard from './RouteCard.svelte';
import { planState } from './planState';
import type { PlanRunDetail } from './api';

afterEach(cleanup);

const outOfDate = planState({
  loading: false,
  planning: false,
  failed: false,
  stale: true,
  readyRunNumber: 7,
  unreadable: false,
});

const ready = planState({
  loading: false,
  planning: false,
  failed: false,
  stale: false,
  readyRunNumber: 7,
  unreadable: false,
});

function run(estimate: boolean, fields: Record<string, unknown> = {}): PlanRunDetail {
  return {
    id: 'r7',
    project_id: 'p',
    number: 7,
    status: 'ready',
    failure_reason: null,
    stops: [],
    totals: null,
    report: null,
    estimate,
    ...fields,
  } as unknown as PlanRunDetail;
}

describe('RouteCard', () => {
  it('shows the status, Real roads, the export of its run and Edit trip', async () => {
    const edit = vi.fn();
    render(RouteCard, {
      props: {
        run: run(false),
        look: ready,
        exportUrl: '/api/plan-runs/r7/export.gpx',
        onedit: edit,
      },
    });

    expect(screen.getByText('Route ready')).toBeInTheDocument();
    expect(screen.getByText('Real roads')).toBeInTheDocument();
    expect(screen.queryByText('Estimate')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Export GPX' })).toHaveAttribute(
      'href',
      '/api/plan-runs/r7/export.gpx',
    );
    await fireEvent.click(screen.getByRole('button', { name: 'Edit trip' }));
    expect(edit).toHaveBeenCalledOnce();
  });

  it('says Estimate, and not Real roads, for a run on the offline road map', () => {
    render(RouteCard, {
      props: { run: run(true), look: ready, exportUrl: '/x', onedit: () => {} },
    });

    expect(screen.getByRole('note', { name: /^estimate:/ })).toHaveTextContent('Estimate');
    expect(screen.queryByText('Real roads')).not.toBeInTheDocument();
  });

  it('offers no export without an address, as while a job runs', () => {
    render(RouteCard, {
      props: { run: run(false), look: ready, exportUrl: undefined, onedit: () => {} },
    });

    expect(screen.queryByRole('link', { name: 'Export GPX' })).not.toBeInTheDocument();
  });

  it("is headed Previous route, with its export, under Couldn't plan", () => {
    render(RouteCard, {
      props: { run: run(false), look: ready, previous: true, exportUrl: '/old', onedit: () => {} },
    });

    expect(screen.getByText('Previous route')).toBeInTheDocument();
    expect(screen.queryByText('Route ready')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Export GPX' })).toHaveAttribute('href', '/old');
  });

  it.each([
    ['stopped', true],
    ['time_limit', true],
    [null, false],
    [undefined, false],
  ])('shows the Not fully optimised tag only for a run that says %s', (code, tagged) => {
    render(RouteCard, {
      props: {
        run: run(false, { not_fully_optimised: code }),
        look: ready,
        exportUrl: '/x',
        onedit: () => {},
      },
    });

    expect(screen.queryByText('Not fully optimised') !== null).toBe(tagged);
  });

  it('makes Plan the route the main action of an out-of-date route, Export GPX staying a secondary one', async () => {
    const plan = vi.fn();
    render(RouteCard, {
      props: {
        run: run(true),
        look: outOfDate,
        exportUrl: '/api/plan-runs/r7/export.gpx',
        onedit: () => {},
        onplan: plan,
      },
    });

    const main = screen.getByRole('button', { name: 'Plan the route' });
    expect(main).toHaveClass('primary');
    const link = screen.getByRole('link', { name: 'Export GPX' });
    expect(link).toHaveAttribute('href', '/api/plan-runs/r7/export.gpx');
    expect(link).not.toHaveClass('primary');
    await fireEvent.click(main);
    expect(plan).toHaveBeenCalledOnce();
  });

  it('keeps Export GPX the main action, and offers no Plan the route, on a route that is up to date', () => {
    render(RouteCard, {
      props: { run: run(false), look: ready, exportUrl: '/x', onedit: () => {}, onplan: () => {} },
    });

    expect(screen.queryByRole('button', { name: 'Plan the route' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Export GPX' })).toHaveClass('primary');
  });
});
