<script lang="ts">
  // The steps of a running rebuild (US-30): those done are ticked, the one it is in is marked, the rest are still to
  // come; from the building step the minutes left, counted to the time the planner says planning is back. Only words
  // and marks: the step and the figures are the planner's own.
  import { remainingText, stepMarks } from './roadMapView';

  let {
    step,
    stepsDone,
    backAt,
    now,
  }: { step: string | null; stepsDone: number; backAt: string | null; now: number } = $props();

  const DONE = ' done'; // said for a ticked step, which the tick alone does not tell a screen reader
  const marks = $derived(stepMarks(step, stepsDone));
  const left = $derived(remainingText(step, backAt, now));
</script>

<section aria-label="Rebuild progress">
  <ol>
    {#each marks as { label, mark } (label)}
      <li class={mark} aria-current={mark === 'current' ? 'step' : undefined}>
        {label}{#if mark === 'done'}<span class="sr">{DONE}</span>{/if}
      </li>
    {/each}
  </ol>
  {#if left}
    <p>{left}</p>
  {/if}
</section>

<style>
  ol {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--color-text-muted);
  }
  li::before {
    content: '\25CB';
  }
  li.done::before {
    content: '\2713';
    color: var(--color-success-fg);
  }
  li.current {
    color: var(--color-text);
    font-weight: 600;
  }
  li.current::before {
    content: '\25CF';
    color: var(--color-info-fg);
  }
  p {
    margin: var(--space-2) 0 0;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
</style>
