<script lang="ts">
  // The stops of a plan run as steps, in order (FR-6.1, D286): each a button (44 px) with the stop's number as the map
  // has it (the itinerary position + 1; S and E for the Start and the End), the name, the type word (Trail, Place; a
  // retrace reads 'Back the same way' and keeps the planner's reason), the road leg, a trail's length and off-road
  // time, and the Unconfirmed warning of a reason. The cumulative km and the entry and exit coordinates are in the
  // step's title, and in the GPX. A run stored before the per-stop columns shows only what it has. The page holds the
  // selected stop: a press tells it, and a stop picked on the map scrolls its step into view.
  import type { PlanStop, Point } from './api';
  import { durationText } from './duration';
  import { legKmText } from './legKm';

  let {
    stops,
    selected = undefined,
    onselect,
  }: {
    stops: PlanStop[];
    selected?: number | undefined;
    onselect?: (stop: number) => void;
  } = $props();

  const TYPE_TEXTS: Record<PlanStop['type'], string> = {
    track: 'Trail',
    poi: 'Place',
    retrace: 'Back the same way',
  };

  let buttons: Record<number, HTMLButtonElement | undefined> = {};
  let pressed: number | undefined; // the step pressed here: the page's answer needs no scrolling

  function coordinates({ lat, lon }: Point): string {
    return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  }

  /** `seconds` is null for a run stored before the per-stop columns (05-07), and absent in an older answer still. */
  function distanceAndTime(km: number, seconds: number | null | undefined): string {
    return seconds == null ? legKmText(km) : `${legKmText(km)}, ${durationText(seconds)}`;
  }

  function disc(position: number): string {
    if (position === 0) return 'S';
    return position === stops.length - 1 ? 'E' : String(position + 1);
  }

  function titleOf(stop: PlanStop): string {
    const parts = [];
    if (stop.cumulative_km != null)
      parts.push(`Cumulative ${distanceAndTime(stop.cumulative_km, stop.cumulative_s)}`);
    if (stop.entry && stop.exit)
      parts.push(`${coordinates(stop.entry)} -> ${coordinates(stop.exit)}`);
    return parts.join('. ');
  }

  function press(number: number): void {
    pressed = number;
    onselect?.(number);
  }

  $effect(() => {
    const stop = selected;
    if (stop === undefined) return;
    if (stop !== pressed) buttons[stop]?.scrollIntoView({ block: 'nearest' });
    pressed = undefined;
  });
</script>

<ol aria-label="Itinerary">
  {#each stops as stop, position (position)}
    <li>
      <button
        type="button"
        class="step"
        aria-current={selected === position + 1 ? 'step' : undefined}
        title={titleOf(stop) || undefined}
        bind:this={buttons[position + 1]}
        onclick={() => press(position + 1)}
      >
        <span class="disc">{disc(position)}</span>
        <span class="body">
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
            <span class="line">Trail {distanceAndTime(stop.track_km, stop.offroad_s)} off-road</span
            >
          {/if}
        </span>
      </button>
    </li>
  {/each}
</ol>

<style>
  ol {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    min-width: 0;
  }
  .step {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
    box-sizing: border-box;
    width: 100%;
    min-width: 44px;
    min-height: 44px;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    color: var(--color-text);
    text-align: left;
    overflow-wrap: anywhere;
  }
  .step[aria-current='step'] {
    border-color: var(--color-accent);
    box-shadow: inset 0 0 0 2px var(--color-accent);
  }
  .disc {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    min-width: 1.75rem;
    height: 1.75rem;
    padding: 0 var(--space-1);
    border-radius: var(--radius-pill);
    background: var(--color-accent);
    color: var(--color-on-accent);
    font-weight: 700;
    box-sizing: border-box;
  }
  .body {
    min-width: 0;
  }
  .name {
    font-weight: 600;
  }
  .type {
    margin-left: var(--space-2);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  .line {
    display: block;
    color: var(--color-text-muted);
  }
  .unconfirmed {
    color: var(--color-warning-fg);
  }
</style>
