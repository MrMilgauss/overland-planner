import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App.svelte';

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = '';
});

describe('App routing', () => {
  it('opens the home page, not a blank app, for a hash that is not valid percent-encoding', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url === '/api/diagnostics'
          ? new Response(
              JSON.stringify({ k2: { invariant_violations: { all_time: 0, window: 0 } } }),
            )
          : new Response(
              url === '/api/health' ? '{"status":"healthy","components":{},"banners":[]}' : '[]',
            ),
      ),
    );
    window.location.hash = '#/projects/%E0';

    render(App);

    expect(screen.getByRole('heading', { name: 'Projects' })).toBeInTheDocument();
  });

  it('has the Road map link beside Projects and Diagnostics and opens its screen on #/road-map', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              served: { known: false, map_date: null, regions: [], total_bytes: 0 },
            }),
          ),
      ),
    );
    window.location.hash = '#/road-map';

    render(App);

    const links = within(screen.getByRole('navigation', { name: 'Main' })).getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual(['Projects', 'Road map', 'Diagnostics']);
    expect(screen.getByRole('heading', { name: 'Road map' })).toBeInTheDocument();
  });
});
