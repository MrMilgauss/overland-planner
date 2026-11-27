<script module lang="ts">
  /** Names joined with commas and "and" ("Italy, Spain and Austria"). */
  export function joinedNames(names: string[]): string {
    return names.length < 2
      ? names.join('')
      : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
  }

  /** The map's day as the page says it ("27 November 2026"), in UTC as the planner dates a map. */
  function dayOf(isoDate: string): string {
    return new Date(isoDate).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: 'UTC',
    });
  }
</script>

<script lang="ts">
  // What the planner's roads cover (US-28 S1, S6), in the heading area of Build the trip: "Roads loaded for: ..." and
  // "Map data: ...", or "Map coverage unknown" (with the date when there is one) and never a guessed list.
  let {
    known,
    regions,
    mapDate,
  }: {
    known: boolean;
    regions: string[];
    /** ISO date-time of the served map, or null. */
    mapDate: string | null;
  } = $props();
</script>

<div class="coverage">
  {#if known}
    <p>Roads loaded for: {joinedNames(regions)}</p>
  {:else}
    <p>Map coverage unknown</p>
  {/if}
  {#if mapDate}
    <p>Map data: {dayOf(mapDate)}</p>
  {/if}
</div>

<style>
  .coverage {
    display: grid;
    gap: var(--space-1, 0.25rem);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  p {
    margin: 0;
  }
</style>
