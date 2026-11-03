<script lang="ts">
  import HealthBanner from './HealthBanner.svelte';
  import { createProject, listProjects, PlannerError } from './api';

  const projects = listProjects();
  let name = $state('');
  let createError = $state('');

  function describe(error: unknown, fallback: string): string {
    return error instanceof PlannerError ? error.message : fallback;
  }

  async function create(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    createError = '';
    try {
      const project = await createProject(name);
      window.location.hash = `#/projects/${encodeURIComponent(project.id)}`;
    } catch (error) {
      createError = describe(error, 'Could not create the project.');
    }
  }
</script>

<main>
  <HealthBanner />
  <h1>Projects</h1>
  <form onsubmit={create}>
    <label for="project-name">Project name</label>
    <input id="project-name" bind:value={name} autocomplete="off" />
    <button type="submit">New project</button>
  </form>
  {#if createError}
    <p role="alert">{createError}</p>
  {/if}
  {#await projects}
    <p aria-busy="true">Loading projects…</p>
  {:then list}
    {#if list.length === 0}
      <p>No projects yet.</p>
    {:else}
      <ul>
        {#each list as project (project.id)}
          <li><a href={`#/projects/${encodeURIComponent(project.id)}`}>{project.name}</a></li>
        {/each}
      </ul>
    {/if}
  {:catch error}
    <p role="alert">{describe(error, 'Could not load projects.')}</p>
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
  form {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }
  label {
    flex-basis: 100%;
  }
  input {
    flex: 1 1 12rem;
    min-width: 0;
    padding: 0.5rem;
    font-size: 1rem;
  }
  button {
    padding: 0.5rem 1rem;
    font-size: 1rem;
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
