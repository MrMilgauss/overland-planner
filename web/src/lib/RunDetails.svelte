<script lang="ts">
  // The engine's details of a ready run (D285), behind one closed Details at the end of Your route: its number, the
  // provider line, the objective, the planner's own lines verbatim and in its order, and Re-optimise when the plan was
  // reused. The web neither parses nor rewords a line (D211). It is closed again whenever another run is shown.
  import type { PlanRunDetail } from './api';
  import { planRunLabel } from './planState';

  let { run, onreoptimise }: { run: PlanRunDetail; onreoptimise: () => void } = $props();
</script>

{#key run.id}
  <details>
    <summary>Details</summary>
    <div class="body">
      <p class="run">{planRunLabel(run.number)}</p>
      {#if run.provider_header}
        <p class="provider">{run.provider_header}</p>
      {/if}
      {#if run.objective_label}
        <p class="objective">{run.objective_label}</p>
      {/if}
      {#each run.messages ?? [] as message, index (index)}
        <p class="message">{message}</p>
      {/each}
      {#if run.memo_hit}
        <button type="button" onclick={onreoptimise}>Re-optimise (ignore previous result)</button>
      {/if}
    </div>
  </details>
{/key}

<style>
  details {
    border-top: 1px solid var(--color-border);
    padding-top: var(--space-2);
  }
  summary {
    display: flex;
    align-items: center;
    min-height: var(--target-min);
    color: var(--color-text-muted);
    cursor: pointer;
  }
  .body {
    display: grid;
    gap: var(--space-1);
    justify-items: start;
    padding-bottom: var(--space-2);
  }
  p {
    margin: 0;
  }
  .run {
    font-weight: 600;
  }
</style>
