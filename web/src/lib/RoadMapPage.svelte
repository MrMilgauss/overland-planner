<script lang="ts">
  // The "Road map" screen (US-27): the regions of the served map with sizes, the total and the map date, or "Map coverage
  // unknown" before the first rebuild from the app. A region found by name is added, and a loaded one removed, as a
  // pending choice held here: the served list is never touched until a rebuild ends well. The preview of the choice
  // gives its size and time (the summary), and a choice above the planner's limit is refused in words and not kept.
  import {
    failureText,
    previewChange,
    readRoadMap,
    type CatalogueRegion,
    type ChangePreview,
    type RoadMapLimits,
    type ServedRoadMap,
  } from './api';
  import ChangeSummary from './ChangeSummary.svelte';
  import RegionSearch from './RegionSearch.svelte';
  import { mapDateText, pendingKeys, sizeText, tooBigText } from './roadMapView';

  let served = $state<ServedRoadMap['served'] | undefined>();
  let failure = $state('');
  let removed = $state<string[]>([]);
  let added = $state<CatalogueRegion[]>([]);
  let summary = $state<ChangePreview | undefined>();
  let limits = $state<RoadMapLimits | undefined>();
  let piOffset = $state(0);
  let refusal = $state('');
  let asked = 0;

  readRoadMap().then(
    (answer) => {
      served = answer.served;
      limits = answer.limits;
      piOffset = answer.server_utc_offset_minutes;
    },
    (error: unknown) => (failure = failureText(error)),
  );

  const addedKeys = $derived(added.map((region) => region.key));

  async function check(keys: string[], undo: () => void): Promise<void> {
    const mine = ++asked;
    refusal = '';
    if (removed.length === 0 && added.length === 0) {
      summary = undefined;
      return;
    }
    try {
      const preview = await previewChange(keys);
      if (mine !== asked) return;
      if (limits && preview.total_bytes > limits.max_bytes) {
        refusal = tooBigText(preview.total_bytes, limits.max_gb);
        undo();
      } else summary = preview;
    } catch (error) {
      if (mine === asked) refusal = failureText(error);
    }
  }

  function change(undo: () => void): void {
    if (served)
      check(
        pendingKeys(
          served.regions.map((r) => r.key),
          removed,
          addedKeys,
        ),
        undo,
      );
  }

  function toggleRemoval(key: string): void {
    const before = removed;
    removed = removed.includes(key) ? removed.filter((k) => k !== key) : [...removed, key];
    change(() => (removed = before));
  }

  function addRegion(region: CatalogueRegion): void {
    const before = added;
    if (!addedKeys.includes(region.key)) added = [...added, region];
    change(() => (added = before));
  }

  function dropAddition(key: string): void {
    const before = added;
    added = added.filter((region) => region.key !== key);
    change(() => (added = before));
  }

  const where = (name: string, parent: string | null, bytes: number | null): string =>
    [name, parent, sizeText(bytes)].filter((part) => part !== null && part !== '').join(', ');
</script>

<h1>Road map</h1>

{#if failure}
  <p role="alert">{failure}</p>
{:else if !served}
  <p>Loading...</p>
{:else}
  {#if served.known}
    <section aria-label="What is loaded">
      <h2>Regions with roads</h2>
      <ul aria-label="Loaded regions">
        {#each served.regions as region (region.key)}
          {@const going = removed.includes(region.key)}
          <li>
            <span class="where">{where(region.name, region.parent_name, region.bytes)}</span>
            {#if going}<span class="tag">to be removed</span>{/if}
            <button
              type="button"
              aria-label={`${going ? 'Keep' : 'Remove'} ${region.name}`}
              onclick={() => toggleRemoval(region.key)}>{going ? 'Keep' : 'Remove'}</button
            >
          </li>
        {/each}
      </ul>
      <p>Total: {sizeText(served.total_bytes)}</p>
    </section>
  {:else}
    <section aria-label="What is loaded">
      <p>Map coverage unknown</p>
      <p class="muted">
        The map was built before the app kept the regions of a map, so they cannot be listed.
        Refreshing the map data builds the same regions again.
      </p>
      <button type="button" disabled>Refresh map data</button>
    </section>
  {/if}
  {#if served.map_date}
    <p>Map data: {mapDateText(served.map_date)}</p>
  {/if}

  {#if served.known}
    {#if added.length > 0}
      <section aria-label="Changes to apply">
        <h2>Pending changes</h2>
        <ul aria-label="Pending changes">
          {#each added as region (region.key)}
            <li>
              <span class="where">{where(region.name, region.parent_name, region.bytes)}</span>
              <span class="tag">to be added</span>
              <button
                type="button"
                aria-label={`Don't add ${region.name}`}
                onclick={() => dropAddition(region.key)}>Don't add</button
              >
            </li>
          {/each}
        </ul>
      </section>
    {/if}
    {#if summary && limits}
      <ChangeSummary {summary} {limits} serverOffsetMinutes={piOffset} choose={() => {}} />
    {/if}
    {#if refusal}
      <p role="alert">{refusal}</p>
    {/if}
    <section aria-label="Find a region">
      <h2>Add a region</h2>
      <RegionSearch chosen={addedKeys} add={addRegion} />
    </section>
  {/if}
{/if}

<style>
  h2 {
    margin: var(--space-4) 0 var(--space-2);
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
    gap: var(--space-2);
  }
  .where {
    flex: 1 1 10rem;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .tag {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
    font-size: var(--text-sm);
  }
  .muted {
    color: var(--color-text-muted);
  }
  p {
    margin: var(--space-2) 0;
  }
</style>
