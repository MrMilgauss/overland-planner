// The Diagnostics page (slice 03, kpi-contracts `diagnostics_endpoint`): GET /api/diagnostics shown as it comes, K2 and
// K3 above 0 in red, G4 green at 0 and amber from 1. The fetch stub stands in for the planner's HTTP API (the port of the page).
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, as steps 04-10 and 05-11); the figures themselves are
// property-tested on the server (DiagnosticsService), so these examples pin only their rendering.
import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DiagnosticsPage from './DiagnosticsPage.svelte';

const RED = 'var(--color-danger-fg)';
const AMBER = 'var(--color-warning-fg)';
const GREEN = 'var(--color-success-fg)';

function diagnostics(fields: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    version: '0.6.0',
    process_started_at: '2026-11-10T07:00:00+00:00',
    days: 30,
    k1: null,
    k2: { invariant_violations: { all_time: 1, window: 0 } },
    k3: { report_omissions: { all_time: 0, window: 0 } },
    k4: null,
    k5: {
      stage_p95_s: { legs: 1.4, solve: 42.6, finalise: null },
      solve_p95_s: { le_30: 42.6 },
      e2e_p95_s: 50.2,
      e2e_p95_by_band_s: { le_30: 50.2 },
      e2e_source: 'elapsed_ms',
      retried_jobs: { le_30: 2, '31_59': 0 },
      second_pass_gt_700_jobs: { le_30: 0 },
      failed_jobs: { le_30: 1 },
      cancelled_jobs: { le_30: 2 },
      memo_hit_jobs: { le_30: 3 },
    },
    k7: { runs_per_project_day: { median: 2.5, max: 4 } },
    g1: null,
    g2: null,
    g4: { engine_refusals_30d: 0 },
    cache_hit_rate_30d: null,
    jobs_by_terminal_state_30d: { done: 12, failed: 1, cancelled: 2, timed_out: 0 },
    retried_jobs_30d: 2,
    second_pass_jobs_30d: 0,
    ...fields,
  };
}

function stubDiagnostics(status: number, body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/api/diagnostics'
        ? new Response(JSON.stringify(body), { status })
        : new Response(JSON.stringify({ code: 'not_found', message: `unexpected ${url}` }), {
            status: 404,
          }),
    ),
  );
}

async function section(name: string): Promise<HTMLElement> {
  return screen.findByRole('region', { name });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Diagnostics page', () => {
  it('shows the stage p95s, retried jobs, jobs by terminal state and variants per project and day', async () => {
    stubDiagnostics(200, diagnostics());
    render(DiagnosticsPage);

    const stages = await section('Stage p95');
    expect(stages).toHaveTextContent('legs: 1.4 s');
    expect(stages).toHaveTextContent('solve: 42.6 s');
    expect(stages).toHaveTextContent('finalise: none');
    const retried = await section('Retried jobs');
    expect(retried).toHaveTextContent('last 30 days: 2');
    expect(retried).toHaveTextContent('le_30: 2');
    const ended = await section('Jobs by terminal state');
    expect(ended).toHaveTextContent('done: 12');
    expect(ended).toHaveTextContent('cancelled: 2');
    expect(ended).toHaveTextContent('timed_out: 0');
    const variants = await section('Variants per project and day');
    expect(variants).toHaveTextContent('median: 2.5');
    expect(variants).toHaveTextContent('max: 4');
  });

  it('shows the K2 and K3 counts, those above 0 in red', async () => {
    stubDiagnostics(200, diagnostics());
    render(DiagnosticsPage);

    const k2 = await section('K2 invariant violations');
    expect(within(k2).getByText('all time: 1')).toHaveStyle({ color: RED });
    expect(within(k2).getByText('all time: 1')).toHaveAttribute('data-role', 'danger'); // the danger badge
    expect(within(k2).getByText('last 30 days: 0')).not.toHaveAttribute('data-role');
    expect(within(k2).getByText('last 30 days: 0')).not.toHaveStyle({ color: RED });
    const k3 = await section('K3 report omissions');
    expect(within(k3).getByText('all time: 0')).not.toHaveStyle({ color: RED });
    expect(within(k3).getByText('last 30 days: 0')).not.toHaveStyle({ color: RED });
  });

  it.each([
    [0, GREEN],
    [1, AMBER],
    [7, AMBER],
  ])('shows %i engine refusals in the window as the colour %s', async (count, colour) => {
    stubDiagnostics(200, diagnostics({ g4: { engine_refusals_30d: count } }));
    render(DiagnosticsPage);

    const g4 = await section('G4 routing engine refusals');
    expect(within(g4).getByText(`last 30 days: ${count}`)).toHaveStyle({ color: colour });
  });

  it('shows none for variants per project and day without a job', async () => {
    stubDiagnostics(
      200,
      diagnostics({ k7: { runs_per_project_day: { median: null, max: null } } }),
    );
    render(DiagnosticsPage);

    const variants = await section('Variants per project and day');
    expect(variants).toHaveTextContent('median: none');
    expect(variants).toHaveTextContent('max: none');
  });

  it("shows the planner's message when the diagnostics cannot be read", async () => {
    stubDiagnostics(500, { code: 'internal', message: 'The planner is restarting' });
    render(DiagnosticsPage);

    expect(await screen.findByRole('alert')).toHaveTextContent('The planner is restarting');
  });
});
