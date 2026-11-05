<script lang="ts">
  // The stops of a plan run, in order: name and road leg; a track also shows its entry and exit, as coordinates (D202).
  import type { PlanStop, Point } from './api';
  import { legKmText } from './legKm';

  let { stops }: { stops: PlanStop[] } = $props();

  function coordinates({ lat, lon }: Point): string {
    return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  }
</script>

<ol aria-label="Itinerary">
  {#each stops as stop, position (position)}
    <li>
      <span class="name">{stop.name}</span>
      {#if stop.leg_km !== null}
        <span class="leg">{legKmText(stop.leg_km)}</span>
      {/if}
      {#if stop.entry && stop.exit}
        <span class="ends">{coordinates(stop.entry)} -&gt; {coordinates(stop.exit)}</span>
      {/if}
    </li>
  {/each}
</ol>

<style>
  ol {
    padding-left: 1.5rem;
  }
  li {
    padding: 0.75rem 0;
    border-bottom: 1px solid #ddd;
  }
  .name {
    font-weight: 600;
  }
  .leg,
  .ends {
    display: block;
    color: #555;
  }
</style>
