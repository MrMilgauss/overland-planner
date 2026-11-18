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
    gap: var(--space-2);
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--color-border);
  }
  .name {
    flex: 1 1 12rem;
    font-weight: 600;
  }
  .type {
    color: var(--color-text-muted);
  }
  .badge {
    padding: 0.1rem var(--space-2);
    border: 1px solid var(--color-success-fg);
    border-radius: var(--radius-pill);
    background: var(--color-success-bg);
    color: var(--color-success-fg);
    font-size: var(--text-sm);
  }
  .anchor {
    border-color: var(--color-info-fg);
    background: var(--color-info-bg);
    color: var(--color-info-fg);
  }
</style>
