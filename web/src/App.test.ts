import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/svelte';
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
});
