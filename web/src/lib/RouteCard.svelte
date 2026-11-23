<script lang="ts">
  // The first route card (D286): the status, whether the roads are real, the 'Not fully optimised' tag, Export GPX (an
  // older run's too, D208) and Edit trip. The totals are large and the road and off-road split stands beside them, each with an edge mark in the map's own line colour; a run stored before the totals has a card without numbers. Out of
  // date: 'Plan the route' is the main action and Export GPX stays, secondary (D259). Under Couldn't plan the older
  // ready run's card is headed 'Previous route'.
  import StatusBadge from './StatusBadge.svelte';
  import { estimateMarker, type PlanLook } from './planState';
  import type { PlanRunDetail } from './api';
  import { durationText } from './duration';
  import { legKmText } from './legKm';
  import { ROAD_COLOUR, TRACK_COLOUR } from './runMap';

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
  const totals = $derived(run.totals ?? null);
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
  {#if totals}
    <dl class="figures" aria-label="Totals">
      <div class="whole">
        <dt>Total</dt>
        <dd class="total">{legKmText(totals.total_km)}</dd>
        <dd class="total">{durationText(totals.total_s)}</dd>
      </div>
      <div class="part" style:border-left-color={ROAD_COLOUR}>
        <dt>Road</dt>
        <dd>{legKmText(totals.road_km)}</dd>
        <dd>{durationText(totals.road_s)}</dd>
      </div>
      <div class="part" style:border-left-color={TRACK_COLOUR}>
        <dt>Off-road</dt>
        <dd>{legKmText(totals.offroad_km)}</dd>
        <dd>{durationText(totals.offroad_s)}</dd>
      </div>
    </dl>
  {/if}
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
  .figures {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2) var(--space-3);
    margin: 0;
  }
  .figures dd,
  .figures dt {
    margin: 0;
  }
  .whole {
    grid-column: 1 / -1;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    align-items: baseline;
  }
  .whole dt {
    flex-basis: 100%;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  .total {
    font-size: var(--text-2xl);
    font-weight: 700;
    line-height: 1.1;
  }
  .part {
    display: grid;
    gap: var(--space-1);
    padding-left: var(--space-2);
    border-left: 4px solid;
  }
  .part dt {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  .part dd {
    font-weight: 600;
  }
</style>
