<script lang="ts">
  // The project's trails and places (D107): type, name, Included and the S/E, Start or End badge.
  import type { Anchor, Item } from './api';

  let { items }: { items: Item[] } = $props();

  const ANCHOR_BADGES: Record<Anchor, string> = { start_end: 'S/E', start: 'Start', end: 'End' };
  const TYPE_LABELS: Record<Item['type'], string> = { track: 'track', poi: 'POI' };
</script>

{#if items.length === 0}
  <p>No trails or places yet.</p>
{:else}
  <ul aria-label="Items">
    {#each items as item (item.id)}
      <li>
        <span class="name">{item.name}</span>
        <span class="type">{TYPE_LABELS[item.type]}</span>
        {#if item.included}<span class="badge">Included</span>{/if}
        {#if item.anchor}<span class="badge anchor">{ANCHOR_BADGES[item.anchor]}</span>{/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul {
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.5rem;
    padding: 0.75rem 0;
    border-bottom: 1px solid #ddd;
  }
  .name {
    flex: 1 1 12rem;
    font-weight: 600;
  }
  .type {
    color: #555;
  }
  .badge {
    padding: 0.1rem 0.5rem;
    border-radius: 1rem;
    background: #e6f0e6;
    font-size: 0.85rem;
  }
  .anchor {
    background: #dde7f7;
  }
</style>
