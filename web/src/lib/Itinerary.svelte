<script lang="ts">
  // The stops of a plan run, in order (FR-6.1): name, type, road leg in km and time, cumulative km and time; a track
  // also shows its length and off-road time and its entry and exit, as coordinates (D202). Then the Totals (FR-6.2).
  // A retrace is its own row: the track driven back, with its reason and its km and time off-road, no Road or Track
  // line; a stop reached by an Unconfirmed road leg is marked with its reason (slice 03b).
  // A run stored before the per-stop columns or the totals shows only what it has. Each line wraps on a narrow phone.
  import type { PlanStop, PlanTotals, Point } from './api';
  import { durationText } from './duration';
  import { legKmText } from './legKm';

  let {
    stops,
    totals = null,
    objectiveLabel = null,
  }: { stops: PlanStop[]; totals?: PlanTotals | null; objectiveLabel?: string | null } = $props();

  const TYPE_TEXTS: Record<PlanStop['type'], string> = {
    track: 'Track',
    poi: 'Place',
    retrace: 'Retrace',
  };

  function coordinates({ lat, lon }: Point): string {
    return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  }

  /** `seconds` is null for a run stored before the per-stop columns (05-07), and absent in an older answer still. */
  function distanceAndTime(km: number, seconds: number | null | undefined): string {
    return seconds == null ? legKmText(km) : `${legKmText(km)}, ${durationText(seconds)}`;
  }
</script>

<ol aria-label="Itinerary">
  {#each stops as stop, position (position)}
    <li>
      <span class="name">{stop.name}</span>
      <span class="type">{TYPE_TEXTS[stop.type]}</span>
      {#if stop.type === 'retrace'}
        <span class="line unconfirmed">Unconfirmed: {stop.reason}</span>
        {#if stop.track_km != null}
          <span class="line">{distanceAndTime(stop.track_km, stop.offroad_s)} off-road</span>
        {/if}
      {/if}
      {#if stop.leg_confidence === 'unconfirmed'}
        <span class="line unconfirmed">Unconfirmed: {stop.leg_reason}</span>
      {/if}
      {#if stop.leg_km !== null}
        <span class="line">Road {distanceAndTime(stop.leg_km, stop.leg_s)}</span>
      {/if}
      {#if stop.type !== 'retrace' && stop.track_km != null}
        <span class="line">Track {distanceAndTime(stop.track_km, stop.offroad_s)} off-road</span>
      {/if}
      {#if stop.cumulative_km != null}
        <span class="line">Cumulative {distanceAndTime(stop.cumulative_km, stop.cumulative_s)}</span
        >
      {/if}
      {#if stop.entry && stop.exit}
        <span class="line">{coordinates(stop.entry)} -&gt; {coordinates(stop.exit)}</span>
      {/if}
    </li>
  {/each}
</ol>

{#if totals}
  <dl aria-label="Totals">
    <div>
      <dt>Road</dt>
      <dd>{distanceAndTime(totals.road_km, totals.road_s)}</dd>
    </div>
    <div>
      <dt>Off-road</dt>
      <dd>{distanceAndTime(totals.offroad_km, totals.offroad_s)}</dd>
    </div>
    <div>
      <dt>Total</dt>
      <dd>{distanceAndTime(totals.total_km, totals.total_s)}</dd>
    </div>
    {#if objectiveLabel}
      <div>
        <dt>Objective</dt>
        <dd class="objective">{objectiveLabel}</dd>
      </div>
    {/if}
  </dl>
{/if}

<style>
  ol {
    padding-left: 1.5rem;
    margin: 0.5rem 0;
  }
  li {
    padding: 0.75rem 0;
    border-bottom: 1px solid #ddd;
    overflow-wrap: anywhere;
  }
  .name {
    font-weight: 600;
  }
  .type {
    margin-left: 0.5rem;
    color: #555;
    font-size: 0.875rem;
  }
  .line {
    display: block;
    color: #555;
  }
  .unconfirmed {
    color: #8a4b00;
  }
  dl {
    margin: 0.5rem 0;
    padding: 0.5rem 0;
  }
  dl div {
    display: flex;
    gap: 0.5rem;
  }
  dt {
    font-weight: 600;
    min-width: 5rem;
  }
  dd {
    margin: 0;
  }
</style>
