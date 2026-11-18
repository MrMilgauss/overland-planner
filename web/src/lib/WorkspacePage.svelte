<script lang="ts">
  // Workspace of one project: import trails (GPX), add places by decimal degrees, set the trip's Start and End.
  // Every refusal of the planner is shown with its own message, verbatim.
  import ItemList from './ItemList.svelte';
  import PlanPanel from './PlanPanel.svelte';
  import RunMap from './RunMap.svelte';
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
  let shownRunId = $state<string | undefined>(); // the ready run the panel shows: the map draws it
  let shownRunIsEstimate = $state(false); // its roads are the offline road map: the map's chip says so
  let panel = $state<{ reload: () => Promise<void> } | undefined>();

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

  /** A place added on the map changes the project: the item list and the panel's runs (now Stale) are read again. */
  async function placeAddedOnMap(): Promise<void> {
    void refresh();
    await panel?.reload();
  }

  open();
</script>

<div class="workspace">
  <div class="heading">
    {#if project}
      <h1>{project.name}</h1>
    {/if}
    {#if problem}
      <p role="alert">{problem}</p>
    {/if}
  </div>

  {#if project}
    <div class="stage">
      {#if shownRunId}
        <RunMap
          planRunId={shownRunId}
          {projectId}
          estimate={shownRunIsEstimate}
          onplaceadded={placeAddedOnMap}
        />
      {:else}
        <p class="placeholder">The map shows the plan once one is computed.</p>
      {/if}
    </div>

    <div class="panel">
      <section class="plan" aria-labelledby="plan-heading">
        <h2 id="plan-heading">Plan</h2>
        <form onsubmit={(event) => event.preventDefault()}>
          <label for="objective">Objective</label>
          <select id="objective" bind:value={objectiveChoice} onchange={chooseObjective}>
            <option value="distance">Minimise road distance</option>
            <option value="time">Minimise road time</option>
          </select>
        </form>
        <PlanPanel
          bind:this={panel}
          {projectId}
          objective={project.objective ?? 'distance'}
          onrunshown={(id, estimate) => {
            shownRunId = id;
            shownRunIsEstimate = estimate;
          }}
        />
      </section>

      <section aria-labelledby="items-heading">
        <h2 id="items-heading">Items</h2>
        <ItemList {items} />
        <h3 id="import-heading">Import trails</h3>
        <form aria-labelledby="import-heading" onsubmit={importFiles}>
          <label for="gpx-files">GPX files</label>
          <input id="gpx-files" type="file" accept=".gpx,application/gpx+xml" multiple bind:files />
          <button type="submit">Import</button>
        </form>
        <h3 id="place-heading">Add a place</h3>
        <form aria-labelledby="place-heading" onsubmit={addThePlace}>
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
        <h2 id="anchors-heading">Start and end</h2>
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
    </div>
  {/if}
</div>

<style>
  /* One column on a phone: title, map (55dvh), panel. Tablet: the map 50dvh, the panel in two columns. Laptop: the map
     fills the main column, the panel has its own width and scrolls on its own (D264). */
  .workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-4);
    padding: var(--space-4);
  }
  .stage {
    height: 55dvh;
    min-height: 16rem;
  }
  .placeholder {
    display: grid;
    place-items: center;
    box-sizing: border-box;
    height: 100%;
    margin: 0;
    padding: var(--space-4);
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    color: var(--color-text-muted);
    text-align: center;
  }
  .panel {
    display: grid;
    gap: var(--space-4);
    min-width: 0;
  }
  section {
    min-width: 0;
  }
  .plan {
    display: grid;
    gap: var(--space-2); /* the Objective control and the panel's controls stand apart */
  }
  form {
    display: grid;
    gap: var(--space-2);
  }
  button {
    justify-self: start;
  }
  h1,
  h2,
  h3 {
    margin: var(--space-2) 0;
  }

  @media (min-width: 600px) {
    .stage {
      height: 50dvh;
    }
    .panel {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-items: start;
    }
    .plan {
      grid-row: span 2;
    }
  }

  @media (min-width: 1024px) {
    .workspace {
      grid-template-columns: minmax(0, 1fr) var(--panel-width);
      grid-template-rows: auto minmax(0, 1fr);
      gap: 0;
      height: calc(100dvh - var(--header-height));
      padding: 0;
    }
    .stage {
      grid-column: 1;
      grid-row: 1 / span 2;
      height: auto;
      min-height: 0;
    }
    .heading {
      grid-column: 2;
      grid-row: 1;
      padding: 0 var(--space-4);
    }
    .panel {
      grid-column: 2;
      grid-row: 2;
      grid-template-columns: minmax(0, 1fr);
      align-content: start;
      overflow-y: auto;
      padding: 0 var(--space-4) var(--space-4);
      border-left: 1px solid var(--color-border);
    }
    .plan {
      grid-row: auto;
    }
  }
</style>
