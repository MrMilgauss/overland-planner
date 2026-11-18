<script lang="ts">
  // Every banner reported by GET /api/health (D108), e.g. a data folder that would not survive a restart.
  import { healthBanners } from './api';

  const banners = healthBanners();
</script>

{#await banners then list}
  {#if list.length > 0}
    <aside aria-label="Planner warnings">
      {#each list as banner (banner)}
        <p>{banner}</p>
      {/each}
    </aside>
  {/if}
{/await}

<style>
  aside {
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
</style>
