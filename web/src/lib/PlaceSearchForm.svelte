<script lang="ts">
  // "Search for a place" of the Add menu (US-29): the typed words go to the planner's place search only when Marco
  // presses Search or Enter, never while typing. Up to five results, each with its region; Add hands the place to the
  // add-place call (the page's) and the form stays open for the next one. A refusal of the add shows beside the
  // results. Search pressed twice in a row sends one search.
  import { failureText, searchPlaces, type NewPlace, type PlaceHit } from './api';

  let { add, close }: { add: (place: NewPlace) => Promise<unknown>; close: () => void } = $props();

  const FINE_PRINT =
    "Only the words you type are sent, from your home connection, to OpenStreetMap's public place search (Nominatim). Your trip and files stay at home. Don't type personal details. Search © OpenStreetMap contributors.";
  const QUICK_MS = 1000;

  let words = $state('');
  let results = $state<PlaceHit[] | undefined>();
  let searched = $state(''); // the words the results are for
  let problem = $state('');
  let busy = $state(false);
  let lastSent = { words: '', at: 0 };

  const label = (hit: PlaceHit): string =>
    [hit.name, hit.region, hit.country].filter((part) => part !== '').join(', ');

  async function search(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const asked = words.trim();
    const now = Date.now();
    if (busy || asked === '') return;
    if (asked === lastSent.words && now - lastSent.at < QUICK_MS) return; // pressed twice quickly
    lastSent = { words: asked, at: now };
    busy = true;
    problem = '';
    try {
      results = (await searchPlaces(asked)).slice(0, 5);
      searched = asked;
    } catch (error) {
      results = undefined;
      problem = failureText(error);
    } finally {
      busy = false;
    }
  }

  async function addHit(hit: PlaceHit): Promise<void> {
    problem = '';
    try {
      await add({ name: hit.name, lat: hit.lat, lon: hit.lon });
    } catch (error) {
      problem = failureText(error);
    }
  }
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && close()} />

<form aria-label="Search for a place" onsubmit={search}>
  <label>
    Place name
    <!-- svelte-ignore a11y_autofocus -->
    <input bind:value={words} autocomplete="off" autofocus />
  </label>
  <span class="buttons">
    <button type="submit" disabled={busy}>Search</button>
    <button type="button" onclick={close}>Close</button>
  </span>
  {#if problem}
    <p role="alert">{problem}</p>
  {/if}
  {#if results && results.length === 0}
    <p role="status">
      No place found for '{searched}'. Try another spelling or add it by clicking on the map.
    </p>
  {/if}
  {#if results && results.length > 0}
    <ul aria-label="Search results">
      {#each results as hit (`${hit.lat},${hit.lon},${hit.name}`)}
        <li>
          <span class="where">{label(hit)}</span>
          <button type="button" onclick={() => addHit(hit)}>Add</button>
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
    flex-wrap: wrap;
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
  p {
    margin: 0;
  }
  .fine {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
</style>
