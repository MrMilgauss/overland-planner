<script lang="ts">
  // Hash routes, no router library: `#/projects/<id>` opens a project's workspace, `#/diagnostics` the Diagnostics page
  // (a hash, since the planner serves no page at other paths); anything else is the home page, with a link to it.
  import DiagnosticsPage from './lib/DiagnosticsPage.svelte';
  import ProjectsPage from './lib/ProjectsPage.svelte';
  import WorkspacePage from './lib/WorkspacePage.svelte';

  const PROJECT_ROUTE = /^#\/projects\/([^/]+)$/;

  let hash = $state(window.location.hash);
  const projectId = $derived(PROJECT_ROUTE.exec(hash)?.[1]);
  const diagnostics = $derived(hash === '#/diagnostics');
</script>

<svelte:window onhashchange={() => (hash = window.location.hash)} />

{#if projectId}
  {#key projectId}
    <WorkspacePage projectId={decodeURIComponent(projectId)} />
  {/key}
{:else if diagnostics}
  <DiagnosticsPage />
{:else}
  <nav><a href="#/diagnostics">Diagnostics</a></nav>
  <ProjectsPage />
{/if}

<style>
  nav {
    padding: 0.5rem 1rem 0;
    text-align: right;
  }
  a {
    font-size: 1rem;
  }
</style>
