<script lang="ts">
  // Hash routes, no router library: `#/projects/<id>` opens a project's workspace, `#/diagnostics` the Diagnostics page
  // (a hash, since the planner serves no page at other paths); anything else is the home page. One header on every page.
  import DiagnosticsPage from './lib/DiagnosticsPage.svelte';
  import ProjectsPage from './lib/ProjectsPage.svelte';
  import WorkspacePage from './lib/WorkspacePage.svelte';

  const PROJECT_ROUTE = /^#\/projects\/([^/]+)$/;

  let hash = $state(window.location.hash);
  /** A hash that is not valid percent-encoding names no project: the home page opens. */
  function decoded(raw: string | undefined): string | undefined {
    try {
      return raw === undefined ? undefined : decodeURIComponent(raw);
    } catch {
      return undefined;
    }
  }
  const projectId = $derived(decoded(PROJECT_ROUTE.exec(hash)?.[1]));
  const diagnostics = $derived(hash === '#/diagnostics');
</script>

<svelte:window onhashchange={() => (hash = window.location.hash)} />

<header>
  <strong>Overland Route Planner</strong>
  <nav aria-label="Main">
    <a class="target" href="#/">Projects</a>
    <a class="target" href="#/diagnostics">Diagnostics</a>
  </nav>
</header>

<main>
  {#if projectId}
    {#key projectId}
      <WorkspacePage {projectId} />
    {/key}
  {:else if diagnostics}
    <DiagnosticsPage />
  {:else}
    <ProjectsPage />
  {/if}
</main>

<style>
  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-4);
    box-sizing: border-box;
    min-height: var(--header-height);
    padding: 0 var(--space-4);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-surface);
  }
  nav {
    display: flex;
    gap: var(--space-4);
  }
  nav a {
    min-width: var(--target-min);
    justify-content: center;
  }
  main {
    max-width: 48rem;
    margin: 0 auto;
    padding: var(--space-4);
  }
</style>
