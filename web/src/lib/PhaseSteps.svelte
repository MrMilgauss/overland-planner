<script lang="ts">
  // The three phases of the trip, in order, the current one marked (D283). 'Your route' is a button back to the result
  // whenever a ready route exists, so that Edit trip is never a dead end.
  import type { TripPhase } from './tripPhase';

  let {
    phase,
    canShowRoute,
    onshowroute,
  }: { phase: TripPhase; canShowRoute: boolean; onshowroute: () => void } = $props();

  const STEPS: { phase: TripPhase; name: string }[] = [
    { phase: 'build', name: 'Build the trip' },
    { phase: 'planning', name: 'Planning' },
    { phase: 'route', name: 'Your route' },
  ];
</script>

<ol class="steps" aria-label="Steps">
  {#each STEPS as step, index (step.phase)}
    <li class:current={step.phase === phase}>
      {#if step.phase === 'route' && canShowRoute}
        <button
          type="button"
          aria-current={step.phase === phase ? 'step' : undefined}
          onclick={onshowroute}
        >
          <span aria-hidden="true">{index + 1}</span>
          {step.name}
        </button>
      {:else}
        <span class="step" aria-current={step.phase === phase ? 'step' : undefined}>
          <span aria-hidden="true">{index + 1}</span>
          {step.name}
        </span>
      {/if}
    </li>
  {/each}
</ol>

<style>
  .steps {
    display: flex;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    flex: 1;
    display: flex;
    border-bottom: 3px solid var(--color-border);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  li.current {
    border-bottom-color: var(--color-accent);
    color: var(--color-text);
    font-weight: 700;
  }
  .step,
  button {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    min-height: 2.75rem;
    text-align: center;
  }
  /* The button reads as its sibling labels: no box, the label's own colour and weight; it shows it can be pressed by
     the pointer cursor and an underline on hover, and by an outline for keyboard focus only. */
  button {
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  button:hover {
    text-decoration: underline;
  }
  button:focus-visible {
    outline: 3px solid var(--color-focus);
    outline-offset: -2px;
  }
</style>
