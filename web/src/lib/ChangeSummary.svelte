<script lang="ts">
  // What a pending road-map change costs, before it is applied (US-27 S5, US-31 S1, S2, S5): the regions added and
  // removed, the size, the estimate with the part during which planning is paused, a region far from the others as
  // information only, then the choice of now or a start time and the rebuild itself. When today's day already has a map the change is refused
  // with the time the next rebuild may start. The planner's figures are only worded here; the choice is handed to the
  // page as the UTC instant, or null for now.
  import type { ChangePreview, RoadMapLimits } from './api';
  import { estimateText, sizeText, startAtUtc, whenText } from './roadMapView';

  let {
    summary,
    limits,
    serverOffsetMinutes,
    choose,
    rebuild,
  }: {
    summary: ChangePreview;
    limits: RoadMapLimits;
    serverOffsetMinutes: number;
    choose: (startAt: string | null) => void;
    rebuild: () => void;
  } = $props();

  let later = $state(false);
  let typed = $state('');

  const names = (regions: { name: string }[]): string => regions.map((r) => r.name).join(', ');
  const startAt = $derived(later ? startAtUtc(typed) : null);

  function pick(atATime: boolean): void {
    later = atATime;
    choose(atATime ? startAtUtc(typed) : null);
  }

  function type(): void {
    choose(startAtUtc(typed));
  }
</script>

<section aria-label="Size and time">
  {#if summary.added.length > 0}<p>Adds {names(summary.added)}</p>{/if}
  {#if summary.removed.length > 0}<p>Removes {names(summary.removed)}</p>{/if}
  <p class="figure">Total download {sizeText(summary.total_bytes)}</p>
  <p>
    Estimate: {estimateText(summary.estimate.total_minutes, summary.estimate.pause_minutes)} (planning
    is paused).
  </p>
  {#if summary.not_linked_note}
    <p role="status">{summary.not_linked_note}</p>
  {/if}

  {#if limits.next_rebuild_from}
    <p role="alert">
      The next rebuild can start from {whenText(limits.next_rebuild_from, serverOffsetMinutes)}.
    </p>
  {:else}
    <fieldset>
      <legend>When to rebuild</legend>
      <label class="choice">
        <input type="radio" name="when" checked={!later} onchange={() => pick(false)} />
        Rebuild now
      </label>
      <label class="choice">
        <input type="radio" name="when" checked={later} onchange={() => pick(true)} />
        Start at a time
      </label>
      {#if later}
        <label class="choice">
          Start time
          <input type="datetime-local" bind:value={typed} oninput={type} />
        </label>
        {#if startAt}
          <p>
            Rebuild at {whenText(startAt, serverOffsetMinutes)}
          </p>
        {/if}
      {/if}
    </fieldset>
    <button type="button" class="primary" disabled={later && startAt === null} onclick={rebuild}
      >Rebuild road map</button
    >
  {/if}
</section>

<style>
  section {
    margin: var(--space-4) 0;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }
  p {
    margin: var(--space-2) 0;
  }
  .figure {
    font-weight: 600;
  }
  fieldset {
    margin: var(--space-3) 0;
    padding: 0;
    border: 0;
  }
  legend {
    padding: 0;
    font-weight: 600;
  }
  .choice {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target-min);
  }
  [role='alert'] {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
  }
</style>
