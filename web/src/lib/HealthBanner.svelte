<script lang="ts">
  // Every banner reported by GET /api/health (D108), e.g. a data folder that would not survive a restart.
  import { healthBanners } from './api';

  const banners = healthBanners();
</script>

{#await banners then list}
  {#if list.length > 0}
    <aside class="banner" aria-label="Planner warnings">
      {#each list as banner (banner)}
        <p>{banner}</p>
      {/each}
    </aside>
  {/if}
{/await}
