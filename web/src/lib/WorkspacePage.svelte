<script lang="ts">
  // Workspace of one project: import trails (GPX), add places by decimal degrees, set the trip's Start and End.
  // Every refusal of the planner is shown with its own message, verbatim.
  import ItemList from './ItemList.svelte';
  import PlanPanel from './PlanPanel.svelte';
  import {
    addPlace,
    failureText,
    importTracks,
    listItems,
    openProject,
    setAnchors,
    setObjective,
    type Objective,
    type Item,
    type Project,
  } from './api';

  let { projectId }: { projectId: string } = $props();

  let project = $state<Project | undefined>();
  let items = $state<Item[]>([]);
  let problem = $state('');
  let files = $state<FileList | undefined>();
  let placeName = $state('');
  let latitude = $state('');
  let longitude = $state('');
  let startId = $state('');
  let endId = $state('');
  let objectiveChoice = $state<Objective>('distance');

  const places = $derived(items.filter((item) => item.type === 'poi'));

  async function refresh(): Promise<void> {
    items = await listItems(projectId);
    startId = items.find((i) => i.anchor === 'start' || i.anchor === 'start_end')?.id ?? startId;
    endId = items.find((i) => i.anchor === 'end' || i.anchor === 'start_end')?.id ?? endId;
  }

  async function attempt(action: () => Promise<unknown>): Promise<boolean> {
    problem = '';
    try {
      await action();
      await refresh();
      return true;
    } catch (error) {
      problem = failureText(error);
      return false;
    }
  }

  async function open(): Promise<void> {
    try {
      project = await openProject(projectId);
      objectiveChoice = project.objective ?? 'distance';
      await refresh();
    } catch (error) {
      problem = failureText(error);
    }
  }

  async function importFiles(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (await attempt(() => importTracks(projectId, Array.from(files ?? [])))) form.reset();
  }

  async function addThePlace(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const place = { name: placeName, lat: Number(latitude), lon: Number(longitude) };
    if (await attempt(() => addPlace(projectId, place))) {
      placeName = '';
      latitude = '';
      longitude = '';
    }
  }

  async function chooseStartAndEnd(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    await attempt(() => setAnchors(projectId, startId, endId));
  }

  /** The choice is the project's value once the planner has taken it; a refusal shows its message and puts the old back. */
  async function chooseObjective(): Promise<void> {
    problem = '';
    try {
      project = await setObjective(projectId, objectiveChoice);
    } catch (error) {
      problem = failureText(error);
    }
    objectiveChoice = project?.objective ?? 'distance';
  }

  open();
</script>

<main>
  <nav><a href="#/">Projects</a></nav>
  {#if project}
    <h1>{project.name}</h1>
  {/if}
  {#if problem}
    <p role="alert">{problem}</p>
  {/if}

  {#if project}
    <section aria-labelledby="items-heading">
      <h2 id="items-heading">Trails and places</h2>
      <ItemList {items} />
    </section>

    <section aria-labelledby="import-heading">
      <h2 id="import-heading">Import trails</h2>
      <form onsubmit={importFiles}>
        <label for="gpx-files">GPX files</label>
        <input id="gpx-files" type="file" accept=".gpx,application/gpx+xml" multiple bind:files />
        <button type="submit">Import</button>
      </form>
    </section>

    <section aria-labelledby="place-heading">
      <h2 id="place-heading">Add a place</h2>
      <form onsubmit={addThePlace}>
        <label for="place-name">Place name</label>
        <input id="place-name" bind:value={placeName} autocomplete="off" />
        <label for="place-lat">Latitude</label>
        <input id="place-lat" bind:value={latitude} inputmode="decimal" placeholder="44.8990" />
        <label for="place-lon">Longitude</label>
        <input id="place-lon" bind:value={longitude} inputmode="decimal" placeholder="6.6430" />
        <button type="submit">Add place</button>
      </form>
    </section>

    <section aria-labelledby="anchors-heading">
      <h2 id="anchors-heading">Start and End</h2>
      <form onsubmit={chooseStartAndEnd}>
        <label for="start-place">Start</label>
        <select id="start-place" bind:value={startId}>
          <option value="" disabled>Choose a place</option>
          {#each places as place (place.id)}
            <option value={place.id}>{place.name}</option>
          {/each}
        </select>
        <label for="end-place">End</label>
        <select id="end-place" bind:value={endId}>
          <option value="" disabled>Choose a place</option>
          {#each places as place (place.id)}
            <option value={place.id}>{place.name}</option>
          {/each}
        </select>
        <button type="submit">Set Start and End</button>
      </form>
    </section>

    <section aria-labelledby="plan-heading">
      <h2 id="plan-heading">Plan</h2>
      <form onsubmit={(event) => event.preventDefault()}>
        <label for="objective">Objective</label>
        <select id="objective" bind:value={objectiveChoice} onchange={chooseObjective}>
          <option value="distance">Minimise road distance</option>
          <option value="time">Minimise road time</option>
        </select>
      </form>
      <PlanPanel {projectId} objective={project.objective ?? 'distance'} />
    </section>
  {/if}
</main>

<style>
  main {
    max-width: 48rem;
    margin: 0 auto;
    padding: 1rem;
    font-family: system-ui, sans-serif;
    overflow-wrap: anywhere;
  }
  section {
    margin-top: 1.5rem;
  }
  h2 {
    font-size: 1.1rem;
  }
  form {
    display: grid;
    gap: 0.4rem;
  }
  input,
  select,
  button {
    min-width: 0;
    padding: 0.5rem;
    font-size: 1rem; /* 16 px: no zoom-on-focus on the iPhone */
  }
  button {
    justify-self: start;
    padding: 0.5rem 1rem;
  }
  [role='alert'] {
    color: #8a1c1c;
  }
</style>
