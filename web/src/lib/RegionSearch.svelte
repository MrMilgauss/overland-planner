<script lang="ts">
  // "Search for a region" of the Road map screen (US-27): the typed words go to the planner's list of regions only when
  // Marco presses Search or Enter, never while typing. Each result shows its parent and size; a region the map has
  // already is marked and a chosen one is not offered twice; Add hands the region to the page, and the form stays.
  import { failureText, searchRegions, type CatalogueRegion } from './api';
  import { sizeText } from './roadMapView';

  let { chosen, add }: { chosen: string[]; add: (region: CatalogueRegion) => void } = $props();

  const FINE_PRINT =
    "Searching asks Geofabrik's public list of regions, from your home connection: the region list, the size of the regions shown and the outline of a chosen one. Only the words you type are used; no trip data leaves.";

  let words = $state('');
  let results = $state<CatalogueRegion[] | undefined>();
  let searched = $state('');
  let problem = $state('');
  let busy = $state(false);

  const label = (region: CatalogueRegion): string =>
    [region.name, region.parent_name, sizeText(region.bytes)]
      .filter((part) => part !== null && part !== '')
      .join(', ');

  async function search(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const asked = words.trim();
    if (busy || asked === '') return;
    busy = true;
    problem = '';
    try {
      results = await searchRegions(asked);
      searched = asked;
    } catch (error) {
      results = undefined;
      problem = failureText(error);
    } finally {
      busy = false;
    }
  }
</script>

<form aria-label="Search for a region" onsubmit={search}>
  <label>
    Region name
    <input bind:value={words} autocomplete="off" />
  </label>
  <span class="buttons"><button type="submit" disabled={busy}>Search</button></span>
  {#if problem}
    <p role="alert">{problem}</p>
  {/if}
  {#if results && results.length === 0}
    <p role="status">No region found for '{searched}'. Try another spelling.</p>
  {/if}
  {#if results && results.length > 0}
    <ul aria-label="Search results">
      {#each results as region (region.key)}
        <li>
          <span class="where">{label(region)}</span>
          {#if region.in_map}
            <span class="tag">Already in the road map</span>
          {:else if chosen.includes(region.key)}
            <span class="tag">To be added</span>
          {:else}
            <button type="button" aria-label={`Add ${region.name}`} onclick={() => add(region)}
              >Add</button
            >
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
  <p class="fine">{FINE_PRINT}</p>
</form>

<style>
  form {
    display: grid;
    gap: var(--space-2);
    box-sizing: border-box;
    width: 100%;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }
  label {
    display: grid;
    gap: var(--space-1);
  }
  .buttons {
    display: flex;
    gap: var(--space-2);
  }
  ul {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .where {
    flex: 1 1 10rem;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .tag {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  p {
    margin: 0;
  }
  .fine {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
</style>
