<script lang="ts">
  // Workspace of one project: the map of the trip, and the phase panel. Build the trip holds the one list of stops and
  // trails with its Add menu (upload GPX trails, click on the map, type coordinates), Start and End from a place's row
  // menu, and the "Plan for" switch. Every refusal of the planner is shown with its own message, verbatim.
  import AddMenu from './AddMenu.svelte';
  import PlanPanel from './PlanPanel.svelte';
  import TripList from './TripList.svelte';
  import TripMap from './TripMap.svelte';
  import {
    addPlace,
    failureText,
    importTracks,
    listItems,
    openProject,
    removeItem,
    setAnchors,
    setObjective,
    type NewPlace,
    type Objective,
    type Item,
    type Project,
  } from './api';

  let { projectId }: { projectId: string } = $props();

  let project = $state<Project | undefined>();
  let items = $state<Item[]>([]);
  let itemsRead = $state(false); // the trip is known and the panel has read the runs: the map draws once, not first empty
  let runsRead = $state(false);
  let problem = $state('');
  let clickMode = $state(false); // the map's "Click on map to add", also put on by the Add menu
  let shownRunId = $state<string | undefined>(); // the ready run the panel shows (Your route): the map draws it
  let shownRunIsEstimate = $state(false); // its roads are the offline road map: the map's chip says so
  let selectedStop = $state<number | undefined>(); // the itinerary step or the map's number marker picked, on the shown run
  let planning = $state(false); // the panel is on Planning: the trip is read-only
  let stage = $state<HTMLElement | undefined>();
  let panel = $state<{ reload: () => Promise<void>; edit: () => void } | undefined>();

  const objective = $derived<Objective>(project?.objective ?? 'distance');
  const OBJECTIVES: [Objective, string][] = [
    ['distance', 'Shortest distance'],
    ['time', 'Shortest time'],
  ];

  async function refresh(): Promise<void> {
    items = await listItems(projectId);
  }

  /** A step pressed: the map goes to the stop and, on a phone where the map is above the list, comes into view. */
  function stepPressed(stop: number): void {
    selectedStop = stop;
    if (window.matchMedia?.('(max-width: 1023px)').matches)
      stage?.scrollIntoView({ block: 'nearest' });
  }

  /** The trip changed: its list and the panel's runs (the shown route may be out of date now) are read again. */
  async function changed(): Promise<void> {
    await refresh();
    await panel?.reload();
  }

  async function attempt(action: () => Promise<unknown>): Promise<boolean> {
    problem = '';
    try {
      await action();
      await changed();
      return true;
    } catch (error) {
      problem = failureText(error);
      return false;
    }
  }

  async function open(): Promise<void> {
    try {
      project = await openProject(projectId);
      await refresh();
    } catch (error) {
      problem = failureText(error);
    }
    itemsRead = true;
  }

  const upload = (files: File[]): Promise<boolean> => attempt(() => importTracks(projectId, files));

  /** A refusal goes to the form that asks (AddMenu shows it), not to the page. */
  async function typedPlace(place: NewPlace): Promise<void> {
    await addPlace(projectId, place);
    await changed();
  }

  const chooseStartAndEnd = (startId: string, endId: string): Promise<boolean> =>
    attempt(() => setAnchors(projectId, startId, endId));

  /** The row's refusal is shown beside the row by the list, so this one rejects; the list and the panel's runs follow. */
  async function removeFromTrip(item: Item): Promise<void> {
    await removeItem(projectId, item.id);
    await changed();
  }

  /** The choice is the project's value once the planner has taken it; a refusal shows its message and keeps the old. */
  async function chooseObjective(choice: Objective): Promise<void> {
    problem = '';
    try {
      project = await setObjective(projectId, choice);
    } catch (error) {
      problem = failureText(error);
    }
  }

  /** A place added on the map changes the project: the item list and the panel's runs (now Stale) are read again. */
  async function placeAddedOnMap(): Promise<void> {
    void refresh();
    panel?.edit();
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
    <div class="stage" bind:this={stage}>
      {#if itemsRead && runsRead}
        <TripMap
          planRunId={shownRunId}
          {items}
          {projectId}
          canAdd={!planning}
          estimate={shownRunIsEstimate}
          {selectedStop}
          onselectstop={(stop) => (selectedStop = stop)}
          onplaceadded={placeAddedOnMap}
          bind:clickMode
        />
      {/if}
    </div>

    <div class="panel">
      <PlanPanel
        bind:this={panel}
        {projectId}
        {objective}
        {selectedStop}
        onselectstop={stepPressed}
        onrunshown={(id, estimate) => {
          if (id !== shownRunId) selectedStop = undefined;
          shownRunId = id;
          shownRunIsEstimate = estimate;
          runsRead = true;
        }}
        onphase={(phase) => (planning = phase === 'planning')}
        {build}
        {trip}
      />
    </div>
  {/if}
</div>

{#snippet trip()}
  <p class="summary">Your trip cannot be changed while it is planned.</p>
  <TripList {items} readonly />
  <p class="summary">Plan for: {OBJECTIVES.find(([value]) => value === objective)?.[1]}</p>
{/snippet}

{#snippet build()}
  <TripList {items} onanchors={chooseStartAndEnd} onremove={removeFromTrip}>
    <AddMenu onupload={upload} onplace={typedPlace} onclickmap={() => (clickMode = true)} />
  </TripList>
  <div class="switch" role="group" aria-label="Plan for">
    <span class="label">Plan for</span>
    {#each OBJECTIVES as [value, label] (value)}
      <button
        type="button"
        aria-pressed={objective === value}
        onclick={() => chooseObjective(value)}>{label}</button
      >
    {/each}
  </div>
{/snippet}

<style>
  /* One column below 1024 px: title, map (phone 45dvh, tablet 50dvh), the phase panel, whose main action is pinned to
     the bottom of the screen. Laptop: the map fills the main column, the panel has its own width and scrolls on its own,
     its main action pinned to the panel's bottom (D264, D289). */
  .workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-4);
    padding: var(--space-4);
  }
  .stage {
    height: 45dvh;
    min-height: 16rem;
  }
  .panel {
    min-width: 0;
  }
  .summary {
    margin: 0;
    color: var(--color-text-muted);
  }
  .switch {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .label {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  h1 {
    margin: var(--space-2) 0;
  }

  @media (min-width: 600px) {
    .stage {
      height: 50dvh;
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
      overflow-y: auto;
      padding: 0 var(--space-4);
      border-left: 1px solid var(--color-border);
    }
  }
</style>
