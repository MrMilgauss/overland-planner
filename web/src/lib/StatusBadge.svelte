<script lang="ts">
  // One look for a labelled state: a colour role (a token pair), a fill (filled, outline or dashed border) and an
  // optional glyph hidden from readers, so that the states differ without colour too (D266).
  import type { Fill, Tone } from './planState';

  let {
    tone,
    fill,
    label,
    glyph,
    ...rest
  }: { tone: Tone; fill: Fill; label: string; glyph?: string; [attribute: string]: unknown } =
    $props();

  const ink = $derived(tone === 'neutral' ? 'var(--color-text-muted)' : `var(--color-${tone}-fg)`);
  const paper = $derived(tone === 'neutral' ? 'var(--color-surface)' : `var(--color-${tone}-bg)`);
</script>

<span
  class="badge"
  data-role={tone}
  style:color={ink}
  style:background-color={fill === 'filled' ? paper : 'transparent'}
  style:border-color={tone === 'neutral' ? 'var(--color-border)' : ink}
  style:border-style={fill === 'dashed' ? 'dashed' : 'solid'}
  {...rest}
>
  {#if glyph}<span aria-hidden="true">{glyph}</span>{/if}{label}
</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 0 var(--space-3);
    border-width: 1px;
    border-radius: var(--radius-pill);
    font-size: var(--text-sm);
    font-weight: 600;
  }
</style>
