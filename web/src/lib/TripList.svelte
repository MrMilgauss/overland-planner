<script lang="ts">
  // The trip's list (D283, D107): the places and trails of the project, a Start and an End tag on the places that are
  // one, and on every row a menu: a place "Set as start" / "Set as end" / "Remove", a trail "Remove" (which asks first,
  // inside the menu). The menu opens in the page flow, as a block under its row, so that no scrolling panel clips it.
  // The anchors call takes both ids, so a choice made
  // while the other is not yet chosen is kept here with the tag "not saved yet" and sent once both are (a project that
  // has the other saved sends the new one with it). An item that is not included carries the muted tag "Left out". Read-only while the trip is planned: no menu.
  import { tick, type Snippet } from 'svelte';
  import { failureText, type Item } from './api';

  type Role = 'start' | 'end';
  let {
    items,
    readonly = false,
    outsideIds = [],
    onanchors,
    onremove,
    children,
  }: {
    items: Item[];
    readonly?: boolean;
    /** The items outside the planner's road map (tagged, and kept); empty while the map is unknown. */
    outsideIds?: string[];
    /** The anchors call with both ids; true once the planner has taken it. */
    onanchors?: (startId: string, endId: string) => Promise<boolean>;
    /** Takes the item off the trip and reads the trip again; rejects with the planner's refusal. */
    onremove?: (item: Item) => Promise<void>;
    /** What stands beside the heading (the Add control). */
    children?: Snippet;
  } = $props();

  const TYPE_LABELS: Record<Item['type'], string> = { track: 'Trail', poi: 'Place' };

  let pending = $state<{ start?: string; end?: string }>({});
  let menuOf = $state<string | undefined>();
  let toggles: Record<string, HTMLButtonElement | undefined> = {};
  let confirming = $state<string | undefined>(); // the item whose removal the open menu is asking about
  let removing = $state(false);
  let refused = $state<{ id: string; text: string } | undefined>();
  let heading = $state<HTMLElement | undefined>();
  let cancel = $state<HTMLButtonElement | undefined>();

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

  function toggleMenu(item: Item): void {
    confirming = undefined;
    refused = undefined;
    menuOf = menuOf === item.id ? undefined : item.id;
  }

  async function askToRemove(item: Item): Promise<void> {
    confirming = item.id;
    await tick();
    cancel?.focus();
  }

  async function cancelRemoval(item: Item): Promise<void> {
    confirming = undefined;
    await tick();
    toggles[item.id]?.focus();
  }

  /** After a removal the focus goes to the next row's menu button, else the previous row's, else the heading. */
  async function remove(item: Item): Promise<void> {
    if (removing) return;
    const at = items.findIndex((i) => i.id === item.id);
    const neighbour = items[at + 1] ?? items[at - 1];
    removing = true;
    refused = undefined;
    try {
      await onremove?.(item);
    } catch (error) {
      refused = { id: item.id, text: failureText(error) };
      removing = false;
      return;
    }
    removing = false;
    confirming = undefined;
    menuOf = undefined;
    await tick();
    (neighbour ? toggles[neighbour.id] : undefined)?.focus();
    if (!neighbour) heading?.focus();
  }
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key !== 'Escape' || menuOf === undefined) return;
    const toggle = toggles[menuOf];
    menuOf = undefined;
    confirming = undefined;
    toggle?.focus();
  }}
/>

<div class="bar">
  <h3 id="trip-heading" tabindex="-1" bind:this={heading}>Your trip</h3>
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
        {#if outsideIds.includes(item.id)}<span class="outside">Outside road map</span>{/if}
        {#each tagsOf(item) as tag (tag.text)}
          <span class="tag">{tag.text}</span>
          {#if tag.unsaved}<span class="unsaved">not saved yet</span>{/if}
        {/each}
        {#if !readonly}
          <button
            type="button"
            class="dots"
            aria-label={`Actions for ${item.name}`}
            bind:this={toggles[item.id]}
            aria-expanded={menuOf === item.id}
            aria-controls={`actions-${item.id}`}
            onclick={() => toggleMenu(item)}><span aria-hidden="true">⋯</span></button
          >
          {#if menuOf === item.id}
            <div class="actions" id={`actions-${item.id}`}>
              {#if confirming === item.id}
                <p>Remove '{item.name}' from the trip?</p>
                <div class="choices">
                  <button type="button" disabled={removing} onclick={() => remove(item)}
                    >Remove</button
                  >
                  <button
                    type="button"
                    bind:this={cancel}
                    disabled={removing}
                    onclick={() => cancelRemoval(item)}>Cancel</button
                  >
                </div>
              {:else}
                {#if item.type === 'poi'}
                  <button type="button" onclick={() => choose(item, 'start')}>Set as start</button>
                  <button type="button" onclick={() => choose(item, 'end')}>Set as end</button>
                {/if}
                <button type="button" onclick={() => askToRemove(item)}>Remove</button>
              {/if}
              {#if refused?.id === item.id}
                <p role="alert">{refused.text}</p>
              {/if}
            </div>
          {/if}
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
  .outside {
    padding: 0.1rem var(--space-2);
    border: 1px solid var(--color-warning-fg);
    border-radius: var(--radius-sm);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
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
  .dots {
    margin-left: auto; /* at the right end of its line */
  }
  /* The menu is a block of the page flow under its row, full width: nothing is clipped or covered. */
  .actions {
    flex: 1 0 100%;
    display: grid;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }
  .actions > button {
    border: 0;
    border-radius: 0;
    background: transparent;
    text-align: left;
  }
  .actions > button + button {
    border-top: 1px solid var(--color-border);
  }
  .actions p {
    margin: 0;
    padding: var(--space-2);
  }
  .choices {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: 0 var(--space-2) var(--space-2);
  }
</style>
