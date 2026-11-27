<script lang="ts">
  // The "Road map" screen (US-27): the regions of the served map with sizes, the total and the map date, or "Map coverage
  // unknown" before the first rebuild from the app. A region found by name is added, and a loaded one removed, as a
  // pending choice held here: the served list is never touched until a rebuild ends well. The preview of the choice
  // gives its size and time (the summary), and a choice above the planner's limit is refused in words and not kept.
  import {
    cancelChange,
    failureText,
    planChange,
    previewChange,
    readRoadMap,
    type CatalogueRegion,
    type ChangePreview,
    type RoadMapChange,
    type RoadMapLimits,
    type ServedRoadMap,
  } from './api';
  import ChangeSummary from './ChangeSummary.svelte';
  import RebuildProgress from './RebuildProgress.svelte';
  import RegionSearch from './RegionSearch.svelte';
  import { onDestroy } from 'svelte';
  import {
    keepsPolling,
    mapDateText,
    pendingKeys,
    plannedText,
    POLL_MS,
    resultOf,
    sizeText,
    tooBigText,
  } from './roadMapView';

  let served = $state<ServedRoadMap['served'] | undefined>();
  let failure = $state('');
  let removed = $state<string[]>([]);
  let added = $state<CatalogueRegion[]>([]);
  let summary = $state<ChangePreview | undefined>();
  let limits = $state<RoadMapLimits | undefined>();
  let piOffset = $state(0);
  let refusal = $state('');
  let planned = $state<RoadMapChange | undefined>();
  let backAt = $state<string | null>(null);
  let now = $state(Date.now());
  let cancelRefusal = $state('');
  let refreshing = $state(false);
  let ended = $state<ReturnType<typeof resultOf>>(null);
  let startAt: string | null = null;
  let seeded = false;
  let asked = 0;

  // The planner is asked once on open, and again every 10 seconds while a change is planned or running.
  let nextRead: ReturnType<typeof setTimeout> | undefined;
  let gone = false;
  onDestroy(() => {
    gone = true;
    clearTimeout(nextRead);
  });

  function read(): Promise<void> {
    clearTimeout(nextRead);
    return readRoadMap().then(
      (answer) => {
        failure = '';
        now = Date.now();
        backAt = answer.planning_back_at;
        served = answer.served;
        limits = answer.limits;
        piOffset = answer.server_utc_offset_minutes;
        planned = answer.change && keepsPolling(answer.change.state) ? answer.change : undefined;
        ended = answer.change ? resultOf(answer.change) : null;
        if (!seeded) {
          seeded = true;
          if (answer.change?.state === 'failed') keepChange(answer.change);
        }
        if (planned && !gone) nextRead = setTimeout(() => void read(), POLL_MS);
      },
      (error: unknown) => {
        failure = failureText(error);
        // a change that is planned or running goes on whatever one read says: the next read may answer
        if (planned && !gone) nextRead = setTimeout(() => void read(), POLL_MS);
      },
    );
  }
  read();

  // A failed rebuild keeps its change: it comes back as the pending choice, so "Rebuild road map" can be pressed again.
  function keepChange(kept: RoadMapChange): void {
    if (kept.added.length === 0 && kept.removed.length === 0) return;
    removed = kept.removed.map((region) => region.key);
    added = kept.added.map((region) => ({
      key: region.key,
      name: region.name,
      parent_name: null,
      bytes: null,
      in_map: false,
    }));
    change(clearChoice);
  }

  function clearChoice(): void {
    removed = [];
    added = [];
  }

  // Why no change is offered: the planner says so (no folder for changes, or a helper not seen for five minutes).
  const unavailable = $derived(
    !limits
      ? ''
      : !limits.changes_available
        ? "Changing the road map isn't available right now"
        : !limits.rebuilds_set_up
          ? "Rebuilds aren't set up on the Pi yet"
          : '',
  );

  const addedKeys = $derived(added.map((region) => region.key));
  // a rebuild needs a region to hold: removing every region is refused by the planner, so it is not offered
  const leavesNone = $derived(
    served !== undefined &&
      served.known &&
      pendingKeys(
        served.regions.map((region) => region.key),
        removed,
        addedKeys,
      ).length === 0,
  );
  const servedKeys = $derived(served?.regions.map((region) => region.key) ?? []);

  async function check(keys: string[], undo: () => void): Promise<void> {
    const mine = ++asked;
    refusal = '';
    if (removed.length === 0 && added.length === 0 && !refreshing) {
      summary = undefined;
      startAt = null;
      return;
    }
    try {
      const preview = await previewChange(refreshing && keys.length === 0 ? undefined : keys);
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
    if (served) check(pendingKeys(servedKeys, removed, addedKeys), undo);
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

  // "Refresh map data": the same regions again, asked and shown as a change made by hand.
  function refresh(): void {
    refreshing = true;
    check([], () => (refreshing = false));
  }

  function dropRefresh(): void {
    refreshing = false;
    summary = undefined;
    refusal = '';
  }

  // Only the planner knows whether this change may be kept; its refusal is shown as it words it.
  async function rebuild(): Promise<void> {
    refusal = '';
    const asRefresh = refreshing && removed.length === 0 && added.length === 0;
    const keys = pendingKeys(servedKeys, removed, addedKeys);
    try {
      await planChange(asRefresh ? undefined : keys, startAt ?? undefined);
    } catch (error) {
      refusal = failureText(error);
      return;
    }
    clearChoice();
    refreshing = false;
    summary = undefined;
    startAt = null;
    cancelRefusal = '';
    await read();
  }

  async function cancel(): Promise<void> {
    cancelRefusal = '';
    try {
      await cancelChange();
    } catch (error) {
      cancelRefusal = failureText(error);
    }
    await read();
  }

  const where = (name: string, parent: string | null, bytes: number | null): string =>
    [name, parent, sizeText(bytes)].filter((part) => part !== null && part !== '').join(', ');
</script>

<h1>Road map</h1>

{#snippet refreshButton()}
  <button type="button" onclick={refresh}>Refresh map data</button>
{/snippet}

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
            {#if !unavailable}
              <button
                type="button"
                aria-label={`${going ? 'Keep' : 'Remove'} ${region.name}`}
                onclick={() => toggleRemoval(region.key)}>{going ? 'Keep' : 'Remove'}</button
              >
            {/if}
          </li>
        {/each}
      </ul>
      <p>Total: {sizeText(served.total_bytes)}</p>
      {#if !unavailable}{@render refreshButton()}{/if}
    </section>
  {:else}
    <section aria-label="What is loaded">
      <p>Map coverage unknown</p>
      <p class="muted">
        The map was built before the app kept the regions of a map, so they cannot be listed.
        Refreshing the map data builds the same regions again.
      </p>
      {#if !unavailable}{@render refreshButton()}{/if}
    </section>
  {/if}
  {#if served.map_date}
    <p>Map data: {mapDateText(served.map_date)}</p>
  {/if}

  {#if ended}
    <section aria-label="Rebuild result" class={ended.kind}>
      <p role={ended.kind === 'failed' ? 'alert' : 'status'}>{ended.text}</p>
    </section>
  {/if}
  {#if unavailable}
    <p role="status">{unavailable}</p>
  {/if}
  {#if planned}
    <section aria-label="Planned rebuild">
      {#if planned.state === 'running'}
        <p>The rebuild has started</p>
        <RebuildProgress
          step={planned.step ?? null}
          stepsDone={planned.steps_done ?? 0}
          {backAt}
          {now}
        />
      {:else}
        <p>{plannedText(planned.start_at, piOffset)}</p>
        <button type="button" onclick={cancel}>Cancel</button>
      {/if}
      {#if cancelRefusal}
        <p role="alert">{cancelRefusal}</p>
      {/if}
    </section>
  {/if}

  {#if !unavailable}
    {#if refreshing}
      <section aria-label="Refresh">
        <p>
          The map data of the same regions is fetched again.
          <button type="button" onclick={dropRefresh}>Don't refresh</button>
        </p>
      </section>
    {/if}
    {#if served.known && added.length > 0}
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
      <ChangeSummary
        {summary}
        {limits}
        serverOffsetMinutes={piOffset}
        choose={(chosen) => (startAt = chosen)}
        {rebuild}
        canRebuild={!leavesNone}
      />
    {/if}
    {#if refusal}
      <p role="alert">{refusal}</p>
    {/if}
    {#if served.known}
      <section aria-label="Find a region">
        <h2>Add a region</h2>
        <RegionSearch chosen={addedKeys} add={addRegion} />
      </section>
    {/if}
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
  section[aria-label='Rebuild result'].failed {
    border-color: var(--color-warning-fg);
  }
  section[aria-label='Planned rebuild'],
  section[aria-label='Rebuild result'] {
    margin: var(--space-4) 0;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }
  .muted {
    color: var(--color-text-muted);
  }
  p {
    margin: var(--space-2) 0;
  }
</style>
