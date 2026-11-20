<script lang="ts">
  // The small form that names a place clicked on the map (slice 09, step 10-05). Add hands the name to the map's `add`
  // and closes when the planner took it; a refusal (an empty name, say) stays here in the planner's own words.
  // Cancel and Escape close it and add nothing. With `coordinates` it also asks for the place's decimal degrees (the
  // Add menu's "Type coordinates") and hands them on as the second argument; without, `add` gets the name alone.
  import { failureText } from './api';

  type Coordinates = { latitude: string; longitude: string };
  let {
    add,
    close,
    coordinates = false,
    label = 'Add a place here',
  }: {
    add: (name: string, coordinates?: Coordinates) => Promise<unknown>;
    close: () => void;
    coordinates?: boolean;
    label?: string;
  } = $props();

  let name = $state('');
  let latitude = $state('');
  let longitude = $state('');
  let problem = $state('');
  let busy = $state(false);

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy) return; // a second submit while one is in flight adds nothing
    busy = true;
    problem = '';
    try {
      if (coordinates) await add(name, { latitude, longitude });
      else await add(name);
      close();
    } catch (error) {
      problem = failureText(error);
    } finally {
      busy = false;
    }
  }
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && close()} />

<form aria-label={label} onsubmit={submit}>
  <label>
    Name
    <!-- svelte-ignore a11y_autofocus -->
    <input bind:value={name} autocomplete="off" autofocus />
  </label>
  {#if coordinates}
    <label>
      Latitude
      <input bind:value={latitude} inputmode="decimal" placeholder="44.8990" autocomplete="off" />
    </label>
    <label>
      Longitude
      <input bind:value={longitude} inputmode="decimal" placeholder="6.6430" autocomplete="off" />
    </label>
  {/if}
  {#if problem}
    <p role="alert">{problem}</p>
  {/if}
  <span class="buttons">
    <button type="submit" disabled={busy}>Add</button>
    <button type="button" onclick={close} disabled={busy}>Cancel</button>
  </span>
</form>

<style>
  form {
    display: grid;
    gap: var(--space-2);
    box-sizing: border-box;
    width: 15rem;
    max-width: 100%;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.3);
  }
  label {
    display: grid;
    gap: var(--space-1);
  }
  .buttons {
    display: flex;
    gap: var(--space-2);
  }
  [role='alert'] {
    margin: 0;
  }
</style>
