<script lang="ts">
  import { listProjects, PlannerError } from './api';

  const projects = listProjects();

  function describe(error: unknown): string {
    return error instanceof PlannerError ? error.message : 'Could not load projects.';
  }
</script>

<main>
  <h1>Projects</h1>
  {#await projects}
    <p aria-busy="true">Loading projects…</p>
  {:then list}
    {#if list.length === 0}
      <p>No projects yet.</p>
    {:else}
      <ul>
        {#each list as project (project.id)}
          <li>{project.name}</li>
        {/each}
      </ul>
    {/if}
  {:catch error}
    <p role="alert">{describe(error)}</p>
  {/await}
</main>

<style>
  main {
    max-width: 48rem;
    margin: 0 auto;
    padding: 1rem;
    font-family: system-ui, sans-serif;
    overflow-wrap: anywhere;
  }
  ul {
    padding: 0;
    list-style: none;
  }
  li {
    padding: 0.75rem 0;
    border-bottom: 1px solid #ddd;
  }
  [role='alert'] {
    color: #8a1c1c;
  }
</style>
