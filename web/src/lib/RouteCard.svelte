<script lang="ts">
  // The first route card (D286): the status, whether the roads are real, the 'Not fully optimised' tag, Export GPX (an
  // older run's too, D208) and Edit trip. 12-06 completes it with the totals and the road and off-road split. Out of
  // date: 'Plan the route' is the main action and Export GPX stays, secondary (D259). Under Couldn't plan the older
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
    onplan,
  }: {
    run: PlanRunDetail;
    /** The status of the plan: the badge of the card, but for a previous route. */
    look: PlanLook;
    previous?: boolean;
    /** The export address of this run; undefined while a job is active. */
    exportUrl: string | undefined;
    onedit: () => void;
    /** Plan again; offered as the main action when the route is out of date. */
    onplan?: () => void;
  } = $props();

  const estimate = $derived(estimateMarker(run.estimate));
  const outOfDate = $derived(!previous && look.state === 'stale');
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
    {#if run.not_fully_optimised}
      <StatusBadge tone="warning" fill="outline" label="Not fully optimised" />
    {/if}
  </div>
  <div class="actions">
    {#if outOfDate}
      <button type="button" class="primary" onclick={onplan}>Plan the route</button>
    {/if}
    {#if exportUrl}
      <a class={outOfDate ? 'button' : 'button primary'} href={exportUrl}>Export GPX</a>
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
