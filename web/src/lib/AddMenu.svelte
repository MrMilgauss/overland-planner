<script lang="ts">
  // The one Add control of Build the trip (D283): "Upload GPX trails" (the import call, through a file chooser), "Click
  // on the map" (the map's click mode) and "Type coordinates" (the add-place call, through the name form with its
  // latitude and longitude). The page does the calls; a refusal of a typed place shows in the form in the planner's
  // words, one of an import on the page.
  import type { NewPlace } from './api';
  import PoiClickForm from './PoiClickForm.svelte';

  let {
    onupload,
    onplace,
    onclickmap,
  }: {
    onupload: (files: File[]) => Promise<unknown>;
    onplace: (place: NewPlace) => Promise<unknown>;
    onclickmap: () => void;
  } = $props();

  let open = $state(false);
  let typing = $state(false);
  let chooser = $state<HTMLInputElement | undefined>();
  let toggle = $state<HTMLButtonElement | undefined>();

  const ENTRIES = ['Upload GPX trails', 'Click on the map', 'Type coordinates'] as const;

  function pick(entry: (typeof ENTRIES)[number]): void {
    open = false;
    if (entry === 'Upload GPX trails') chooser?.click();
    else if (entry === 'Click on the map') onclickmap();
    else typing = true;
  }

  async function uploaded(): Promise<void> {
    const files = Array.from(chooser?.files ?? []);
    if (files.length === 0) return;
    await onupload(files);
    if (chooser) chooser.value = ''; // the same file may be chosen again
  }

  const degrees = (text: string): number => (text.trim() === '' ? Number.NaN : Number(text));

  async function typed(
    name: string,
    coordinates?: { latitude: string; longitude: string },
  ): Promise<void> {
    await onplace({
      name,
      lat: degrees(coordinates?.latitude ?? ''),
      lon: degrees(coordinates?.longitude ?? ''),
    });
  }
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key !== 'Escape' || !open) return;
    open = false;
    toggle?.focus();
  }}
/>

<span class="add">
  <button
    type="button"
    bind:this={toggle}
    aria-expanded={open}
    aria-controls="add-options"
    onclick={() => {
      open = !open;
      typing = false;
    }}>Add</button
  >
  {#if open}
    <ul id="add-options" class="options">
      {#each ENTRIES as entry (entry)}
        <li><button type="button" onclick={() => pick(entry)}>{entry}</button></li>
      {/each}
    </ul>
  {/if}
  <input
    bind:this={chooser}
    type="file"
    class="chooser"
    aria-label="GPX files"
    accept=".gpx,application/gpx+xml"
    multiple
    tabindex="-1"
    onchange={uploaded}
  />
</span>
{#if typing}
  <div class="typing">
    <PoiClickForm coordinates label="Type coordinates" add={typed} close={() => (typing = false)} />
  </div>
{/if}

<style>
  /* The wrapper adds no box: the Add button and the menu are items of the heading bar (a wrapping row), so the menu
     wraps under the heading as a full-width block of the page flow and no scrolling panel clips or covers it. */
  .add {
    display: contents;
  }
  .add > button {
    margin-left: auto;
  }
  .options {
    flex: 1 0 100%;
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }
  .options button {
    border: 0;
    border-radius: 0;
    background: transparent;
    text-align: left;
  }
  .options li + li button {
    border-top: 1px solid var(--color-border);
  }
  .chooser {
    display: none;
  }
  .typing {
    flex: 1 1 100%;
    margin: var(--space-2) 0;
  }
</style>
