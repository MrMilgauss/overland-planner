<script lang="ts">
  // The small form that names a place clicked on the map (slice 09, step 10-05). Add hands the name to the map's `add`
  // and closes when the planner took it; a refusal (an empty name, say) stays here in the planner's own words.
  // Cancel and Escape close it and add nothing.
  import { failureText } from './api';

  let { add, close }: { add: (name: string) => Promise<void>; close: () => void } = $props();

  let name = $state('');
  let problem = $state('');
  let busy = $state(false);

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = true;
    problem = '';
    try {
      await add(name);
      close();
    } catch (error) {
      problem = failureText(error);
    } finally {
      busy = false;
    }
  }
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && close()} />

<form aria-label="Add a place here" onsubmit={submit}>
  <label>
    Name
    <!-- svelte-ignore a11y_autofocus -->
    <input bind:value={name} autocomplete="off" autofocus />
  </label>
  {#if problem}
    <p role="alert">{problem}</p>
  {/if}
  <span class="buttons">
    <button type="submit" disabled={busy}>Add</button>
    <button type="button" onclick={close}>Cancel</button>
  </span>
</form>

<style>
  form {
    display: grid;
    gap: 0.4rem;
    box-sizing: border-box;
    width: 15rem;
    max-width: 100%;
    padding: 0.6rem;
    border: 1px solid #6b7280;
    border-radius: 0.4rem;
    background: #fff;
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.3);
  }
  label {
    display: grid;
    gap: 0.2rem;
  }
  input,
  button {
    min-width: 0;
    padding: 0.5rem;
    font-size: 1rem; /* 16 px: no zoom-on-focus on the iPhone */
  }
  .buttons {
    display: flex;
    gap: 0.5rem;
  }
  [role='alert'] {
    margin: 0;
    color: #8a1c1c;
  }
</style>
