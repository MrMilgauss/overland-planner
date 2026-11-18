<script lang="ts">
  import HealthBanner from './HealthBanner.svelte';
  import K2Banner from './K2Banner.svelte';
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

<HealthBanner />
<K2Banner />
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

<style>
  form {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
  }
  label {
    flex-basis: 100%;
  }
  input {
    flex: 1 1 12rem;
  }
  ul {
    padding: 0;
    list-style: none;
  }
  li {
    border-bottom: 1px solid var(--color-border);
  }
  li a {
    display: flex;
    align-items: center;
    min-height: var(--target-min);
  }
</style>
