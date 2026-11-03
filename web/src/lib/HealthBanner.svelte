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
    margin: 0 0 1rem;
    padding: 0.5rem 0.75rem;
    border: 1px solid #b26b00;
    border-radius: 0.25rem;
    background: #fff4e0;
    color: #5c3600;
  }
  p {
    margin: 0.25rem 0;
  }
</style>
