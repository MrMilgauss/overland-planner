import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ProjectsPage from './ProjectsPage.svelte';

function stubProjectsEndpoint(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const fetchStub = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetchStub);
  return fetchStub;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Projects home page', () => {
  it('shows the Projects heading and the listed project names', async () => {
    const fetchStub = stubProjectsEndpoint(200, [
      { id: 'p1', name: 'Sardinia loop' },
      { id: 'p2', name: 'Alpine passes' },
    ]);

    render(ProjectsPage);

    expect(screen.getByRole('heading', { name: 'Projects' })).toBeInTheDocument();
    expect(await screen.findByText('Sardinia loop')).toBeInTheDocument();
    expect(screen.getByText('Alpine passes')).toBeInTheDocument();
    expect(fetchStub).toHaveBeenCalledWith('/api/projects', expect.anything());
  });

  it('shows an empty-state message when there are no projects', async () => {
    stubProjectsEndpoint(200, []);

    render(ProjectsPage);

    expect(await screen.findByText(/no projects yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it.each([
    [
      'the planner explains the failure',
      503,
      { code: 'unavailable', message: 'Planner is starting up' },
      'Planner is starting up',
    ],
    ['the planner gives no explanation', 500, 'oops', 'Could not load projects'],
  ])(
    'shows an error state when projects cannot be loaded: %s',
    async (_case, status, body, expected) => {
      stubProjectsEndpoint(status, body);

      render(ProjectsPage);

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent(expected);
      expect(screen.getByRole('heading', { name: 'Projects' })).toBeInTheDocument();
    },
  );

  it('shows an error state when the planner cannot be reached', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    );

    render(ProjectsPage);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load projects');
  });
});
