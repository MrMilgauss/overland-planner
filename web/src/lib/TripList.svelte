<script lang="ts">
  // The trip's list (D283, D107): the places and trails of the project, a Start and an End tag on the places that are
  // one, and on a place a row menu "Set as start" / "Set as end". The anchors call takes both ids, so a choice made
  // while the other is not yet chosen is kept here with the tag "not saved yet" and sent once both are (a project that
  // has the other saved sends the new one with it). An item that is not included carries the muted tag "Left out". Read-only while the trip is planned: no menu.
  import type { Snippet } from 'svelte';
  import type { Item } from './api';

  type Role = 'start' | 'end';
  let {
    items,
    readonly = false,
    onanchors,
    children,
  }: {
    items: Item[];
    readonly?: boolean;
    /** The anchors call with both ids; true once the planner has taken it. */
    onanchors?: (startId: string, endId: string) => Promise<boolean>;
    /** What stands beside the heading (the Add control). */
    children?: Snippet;
  } = $props();

  const TYPE_LABELS: Record<Item['type'], string> = { track: 'Trail', poi: 'Place' };

  let pending = $state<{ start?: string; end?: string }>({});
  let menuOf = $state<string | undefined>();

  const saved = $derived({
    start: items.find((i) => i.anchor === 'start' || i.anchor === 'start_end')?.id,
    end: items.find((i) => i.anchor === 'end' || i.anchor === 'start_end')?.id,
  });
  const chosen = $derived({
    start: pending.start ?? saved.start,
    end: pending.end ?? saved.end,
  });

  function tagsOf(item: Item): { text: string; unsaved: boolean }[] {
    return (['start', 'end'] as Role[])
      .filter((role) => chosen[role] === item.id)
      .map((role) => ({
        text: role === 'start' ? 'Start' : 'End',
        unsaved: pending[role] === item.id,
      }));
  }

  async function choose(item: Item, role: Role): Promise<void> {
    menuOf = undefined;
    const next = { ...chosen, [role]: item.id };
    if (next.start === undefined || next.end === undefined) {
      pending = { ...pending, [role]: item.id };
      return;
    }
    pending = { ...pending, [role]: item.id };
    if (await onanchors?.(next.start, next.end)) pending = {};
  }
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && (menuOf = undefined)} />

<div class="bar">
  <h3 id="trip-heading">Your trip</h3>
  {@render children?.()}
</div>
{#if items.length === 0}
  <p>No trails or places yet.</p>
{:else}
  <ul aria-labelledby="trip-heading">
    {#each items as item (item.id)}
      <li>
        <span class="name">{item.name}</span>
        <span class="type">{TYPE_LABELS[item.type]}</span>
        {#if !item.included}<span class="left-out">Left out</span>{/if}
        {#each tagsOf(item) as tag (tag.text)}
          <span class="tag">{tag.text}</span>
          {#if tag.unsaved}<span class="unsaved">not saved yet</span>{/if}
        {/each}
        {#if !readonly && item.type === 'poi'}
          <span class="more">
            <button
              type="button"
              class="dots"
              aria-label={`Actions for ${item.name}`}
              aria-haspopup="menu"
              aria-expanded={menuOf === item.id}
              onclick={() => (menuOf = menuOf === item.id ? undefined : item.id)}
              ><span aria-hidden="true">⋯</span></button
            >
            {#if menuOf === item.id}
              <div role="menu" aria-label={`Actions for ${item.name}`}>
                <button type="button" role="menuitem" onclick={() => choose(item, 'start')}
                  >Set as start</button
                >
                <button type="button" role="menuitem" onclick={() => choose(item, 'end')}
                  >Set as end</button
                >
              </div>
            {/if}
          </span>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  .bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  h3 {
    margin: var(--space-2) 0;
  }
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--color-border);
  }
  .name {
    flex: 1 1 10rem;
    font-weight: 600;
  }
  .type {
    color: var(--color-text-muted);
  }
  .tag {
    padding: 0.1rem var(--space-2);
    border: 1px solid var(--color-info-fg);
    border-radius: var(--radius-sm);
    background: var(--color-info-bg);
    color: var(--color-info-fg);
    font-size: var(--text-sm);
    font-weight: 700;
  }
  .left-out {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
  .unsaved {
    color: var(--color-warning-fg);
    font-size: var(--text-sm);
  }
  .more {
    position: relative;
    margin-left: auto; /* at the right end of its line, so that its menu opens inside the panel */
  }
  [role='menu'] {
    position: absolute;
    top: 100%;
    right: 0;
    z-index: 3;
    display: grid;
    min-width: 11rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    box-shadow: 0 6px 18px rgb(0 0 0 / 0.25);
  }
  [role='menu'] button {
    border: 0;
    border-radius: 0;
    background: transparent;
    text-align: left;
  }
  [role='menu'] button + button {
    border-top: 1px solid var(--color-border);
  }
</style>
