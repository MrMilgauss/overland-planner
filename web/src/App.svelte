<script lang="ts">
  // Hash routes, no router library: `#/projects/<id>` opens a project's workspace; anything else is the home page.
  import ProjectsPage from './lib/ProjectsPage.svelte';
  import WorkspacePage from './lib/WorkspacePage.svelte';

  const PROJECT_ROUTE = /^#\/projects\/([^/]+)$/;

  let hash = $state(window.location.hash);
  const projectId = $derived(PROJECT_ROUTE.exec(hash)?.[1]);
</script>

<svelte:window onhashchange={() => (hash = window.location.hash)} />

{#if projectId}
  {#key projectId}
    <WorkspacePage projectId={decodeURIComponent(projectId)} />
  {/key}
{:else}
  <ProjectsPage />
{/if}
