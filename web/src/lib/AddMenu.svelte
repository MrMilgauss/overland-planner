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

<svelte:window onkeydown={(event) => event.key === 'Escape' && (open = false)} />

<span class="add">
  <button
    type="button"
    aria-haspopup="menu"
    aria-expanded={open}
    onclick={() => {
      open = !open;
      typing = false;
    }}>Add</button
  >
  {#if open}
    <div role="menu" aria-label="Add">
      {#each ENTRIES as entry (entry)}
        <button type="button" role="menuitem" onclick={() => pick(entry)}>{entry}</button>
      {/each}
    </div>
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
  .add {
    position: relative;
    margin-left: auto;
  }
  [role='menu'] {
    position: absolute;
    top: 100%;
    right: 0;
    z-index: 3;
    display: grid;
    min-width: 12rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    box-shadow: 0 6px 18px rgb(0 0 0 / 0.25);
  }
  [role='menu'] button {
    border: 0;
    border-radius: 0;
    background: transparent;
    text-align: left;
  }
  [role='menu'] button + button {
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
