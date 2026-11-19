<script lang="ts">
  // The first route card (D286): the status, whether the roads are real, Export GPX (an older run's too, D208) and Edit
  // trip. 12-05 and 12-06 complete it with the totals and the road and off-road split. Under Couldn't plan the older
  // ready run's card is headed 'Previous route'.
  import StatusBadge from './StatusBadge.svelte';
  import { estimateMarker, type PlanLook } from './planState';
  import type { PlanRunDetail } from './api';

  let {
    run,
    look,
    previous = false,
    exportUrl,
    onedit,
  }: {
    run: PlanRunDetail;
    /** The status of the plan: the badge of the card, but for a previous route. */
    look: PlanLook;
    previous?: boolean;
    /** The export address of this run; undefined while a job is active. */
    exportUrl: string | undefined;
    onedit: () => void;
  } = $props();

  const estimate = $derived(estimateMarker(run.estimate));
</script>

<div class="card">
  <div class="pills">
    {#if previous}
      <StatusBadge tone="success" fill="filled" glyph="✓" label="Previous route" />
    {:else}
      <StatusBadge
        tone={look.role}
        fill={look.fill}
        glyph={look.glyph}
        label={look.label}
        data-plan-state={look.state}
      />
    {/if}
    {#if estimate}
      <StatusBadge
        tone={estimate.role}
        fill={estimate.fill}
        glyph={estimate.glyph}
        label={estimate.label}
        role="note"
        title={estimate.note}
        aria-label={estimate.note}
      />
    {:else}
      <StatusBadge tone="success" fill="outline" label="Real roads" />
    {/if}
  </div>
  <div class="actions">
    {#if exportUrl}
      <a class="button primary" href={exportUrl}>Export GPX</a>
    {/if}
    <button type="button" onclick={onedit}>Edit trip</button>
  </div>
</div>

<style>
  .card {
    display: grid;
    gap: var(--space-3);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }
  .pills,
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
  }
</style>
