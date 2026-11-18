<script lang="ts">
  // The all-time count of plan runs that broke a hard rule (K2), shown until this browser acknowledges it (D271).
  import { readDiagnostics } from './api';
  import { K2Acknowledgement } from './k2Acknowledgement';

  const acknowledgement = new K2Acknowledgement();
  let count = $state(0);
  let acknowledged = $state(acknowledgement.acknowledged());

  readDiagnostics().then(
    (diagnostics) => {
      count = diagnostics.k2.invariant_violations.all_time;
    },
    () => {}, // an unreadable count shows nothing
  );

  function acknowledge(): void {
    acknowledgement.acknowledge(count);
    acknowledged = acknowledgement.acknowledged();
  }
</script>

{#if count > acknowledged}
  <aside role="alert">
    <p>
      {count} plan {count === 1 ? 'run' : 'runs'} broke one of the planner's rules.
      <a href="#/diagnostics">Diagnostics</a>
    </p>
    <button type="button" class="primary" onclick={acknowledge}>Acknowledge</button>
  </aside>
{/if}

<style>
  aside {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin: 0 0 var(--space-4);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-warning-fg);
    border-radius: var(--radius-md);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
  }
  p {
    margin: var(--space-1) 0;
  }
  a {
    color: inherit;
    text-decoration: underline;
  }
</style>
