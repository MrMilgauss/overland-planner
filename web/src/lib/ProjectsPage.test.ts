import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ProjectsPage from './ProjectsPage.svelte';

const HEALTHY = { status: 'healthy', components: {}, banners: [] };

/** The planner: GET /api/projects answers `status`/`body`, GET /api/health `health`, POST /api/projects `created`. */
function stubProjectsEndpoint(
  status: number,
  body: unknown,
  health: unknown = HEALTHY,
  created: { status: number; body: unknown } = { status: 201, body: {} },
): ReturnType<typeof vi.fn> {
  const fetchStub = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url === '/api/health') return new Response(JSON.stringify(health), { status: 200 });
    if (init.method === 'POST') {
      return new Response(JSON.stringify(created.body), { status: created.status });
    }
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal('fetch', fetchStub);
  return fetchStub;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = '';
});

describe('Projects home page', () => {
  it('shows the Projects heading and the listed project names', async () => {
    const fetchStub = stubProjectsEndpoint(200, [
      { id: 'p1', name: 'Sardinia loop' },
      { id: 'p2', name: 'Alpine passes' },
    ]);

    render(ProjectsPage);

    expect(screen.getByRole('heading', { name: 'Projects' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Sardinia loop' })).toHaveAttribute(
      'href',
      '#/projects/p1',
    );
    expect(screen.getByRole('link', { name: 'Alpine passes' })).toHaveAttribute(
      'href',
      '#/projects/p2',
    );
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

  it('creates a project from its name and opens its workspace', async () => {
    const fetchStub = stubProjectsEndpoint(200, [], HEALTHY, {
      status: 201,
      body: { id: 'p9', name: 'Alpi Occidentali giugno 2027', revision: 1 },
    });
    render(ProjectsPage);

    await fireEvent.input(screen.getByLabelText('Project name'), {
      target: { value: 'Alpi Occidentali giugno 2027' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'New project' }));

    await vi.waitFor(() => expect(window.location.hash).toBe('#/projects/p9'));
    const post = fetchStub.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(post?.[0]).toBe('/api/projects');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ name: 'Alpi Occidentali giugno 2027' });
  });

  it('shows the planner message verbatim when a project cannot be created', async () => {
    stubProjectsEndpoint(200, [], HEALTHY, {
      status: 422,
      body: { code: 'validation_error', message: 'Give the project a name' },
    });
    render(ProjectsPage);

    await fireEvent.click(screen.getByRole('button', { name: 'New project' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Give the project a name');
    expect(window.location.hash).toBe('');
  });

  it('shows every banner the planner health reports', async () => {
    const banners = [
      'Data directory is not persistent - projects would be lost on restart',
      'Road map is not loaded',
    ];
    stubProjectsEndpoint(200, [], { status: 'unhealthy', components: {}, banners });

    render(ProjectsPage);

    const warnings = await screen.findByRole('complementary', { name: 'Planner warnings' });
    for (const banner of banners) expect(warnings).toHaveTextContent(banner);
  });

  it('shows no warnings while the planner reports no banner', async () => {
    stubProjectsEndpoint(200, []);

    render(ProjectsPage);

    await screen.findByText(/no projects yet/i);
    expect(
      screen.queryByRole('complementary', { name: 'Planner warnings' }),
    ).not.toBeInTheDocument();
  });
});
