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
  k2Count: number | null = 0,
): ReturnType<typeof vi.fn> {
  const fetchStub = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url === '/api/health') return new Response(JSON.stringify(health), { status: 200 });
    if (url === '/api/diagnostics') {
      return k2Count === null
        ? new Response('oops', { status: 503 })
        : new Response(
            JSON.stringify({ k2: { invariant_violations: { all_time: k2Count, window: 0 } } }),
            { status: 200 },
          );
    }
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
  localStorage.clear();
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

describe('K2 banner on the home page', () => {
  const wording = /broke one of the planner's rules/;

  it('shows the count, a link to Diagnostics and Acknowledge, until acknowledged in this browser', async () => {
    const fetchStub = stubProjectsEndpoint(200, [], HEALTHY, undefined, 1);
    const first = render(ProjectsPage);

    const shown = await screen.findByText(wording);
    expect(shown.closest('[role="alert"]')).toHaveTextContent('1');
    expect(screen.getByRole('link', { name: 'Diagnostics' })).toHaveAttribute(
      'href',
      '#/diagnostics',
    );
    const before = fetchStub.mock.calls.length;
    await fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    expect(screen.queryByText(wording)).not.toBeInTheDocument();
    expect(fetchStub.mock.calls.length).toBe(before); // browser only, no request

    first.unmount();
    render(ProjectsPage);
    await screen.findByText(/no projects yet/i);
    expect(screen.queryByText(wording)).not.toBeInTheDocument();
  });

  it('comes back when the count grows past the acknowledged one', async () => {
    localStorage.setItem('k2.acknowledged', '1');
    stubProjectsEndpoint(200, [], HEALTHY, undefined, 2);

    render(ProjectsPage);

    expect((await screen.findByText(wording)).closest('[role="alert"]')).toHaveTextContent('2');
  });

  it.each([
    ['no rule was broken', 0],
    ['the count cannot be read', null],
  ])('shows no banner and still lists the projects when %s', async (_case, count) => {
    stubProjectsEndpoint(200, [{ id: 'p1', name: 'Sardinia loop' }], HEALTHY, undefined, count);

    render(ProjectsPage);

    expect(await screen.findByRole('link', { name: 'Sardinia loop' })).toBeInTheDocument();
    await vi.waitFor(() =>
      expect(fetch).toHaveBeenCalledWith('/api/diagnostics', expect.anything()),
    );
    expect(screen.queryByText(wording)).not.toBeInTheDocument();
  });

  it('still shows the banner when the browser refuses to keep anything', async () => {
    const refuse = vi.fn(() => {
      throw new DOMException('refused', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(refuse);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(refuse);
    stubProjectsEndpoint(200, [], HEALTHY, undefined, 1);

    render(ProjectsPage);
    await screen.findByText(wording);
    await fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));

    expect(screen.getByText(wording)).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
