<script lang="ts">
  // GET /api/diagnostics as it comes (kpi-contracts `diagnostics_endpoint`): the stage p95s, the retried jobs, the jobs
  // by terminal state, the variants per project and day, the K2 and K3 counts, any above 0 in a red badge, and the G4
  // count of refusals for the routing engine, green at 0 and amber from 1. Keys are the planner's own (stages, bands,
  // states); seconds to one decimal; a figure without a job shows 'none'.
  import StatusBadge from './StatusBadge.svelte';
  import { failureText, readDiagnostics, type Diagnostics, type WindowCount } from './api';

  const NONE = 'none';
  const AMBER = 'var(--color-warning-fg)'; // G4 from 1: plans were refused while the routing engine was down or loading
  const GREEN = 'var(--color-success-fg)'; // G4 at 0
  const report = readDiagnostics();

  function seconds(value: number | null): string {
    return value === null ? NONE : `${value.toFixed(1)} s`;
  }

  function figure(value: number | null): string {
    return value === null ? NONE : String(value);
  }

  /** K2 and K3: the plan runs that broke a hard rule, and those whose report left out an item. */
  function runChecks(diagnostics: Diagnostics): [string, WindowCount][] {
    return [
      ['K2 invariant violations', diagnostics.k2.invariant_violations],
      ['K3 report omissions', diagnostics.k3.report_omissions],
    ];
  }

  function counts(days: number, count: WindowCount): [string, number][] {
    return [
      ['all time', count.all_time],
      [`last ${days} days`, count.window],
    ];
  }
</script>

<h1>Diagnostics</h1>

{#await report}
  <p>Loading...</p>
{:then diagnostics}
  <p class="meta">
    Version {diagnostics.version}, started {diagnostics.process_started_at}, last {diagnostics.days}
    days
  </p>

  {#each runChecks(diagnostics) as [title, count] (title)}
    <section aria-label={title}>
      <h2>{title}</h2>
      <ul>
        {#each counts(diagnostics.days, count) as [label, value] (label)}
          <li class:alarm={value > 0}>
            {#if value > 0}
              <StatusBadge tone="danger" fill="filled" glyph="✕" label={`${label}: ${value}`} />
            {:else}
              {label}: {value}
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/each}

  <section aria-label="G4 routing engine refusals">
    <h2>G4 routing engine refusals</h2>
    <ul>
      <li
        class:alarm={diagnostics.g4.engine_refusals_30d > 0}
        style:color={diagnostics.g4.engine_refusals_30d > 0 ? AMBER : GREEN}
      >
        last {diagnostics.days} days: {diagnostics.g4.engine_refusals_30d}
      </li>
    </ul>
  </section>

  <section aria-label="Stage p95">
    <h2>Stage p95</h2>
    <ul>
      {#each Object.entries(diagnostics.k5.stage_p95_s) as [stage, value] (stage)}
        <li>{stage}: {seconds(value)}</li>
      {/each}
    </ul>
  </section>

  <section aria-label="Retried jobs">
    <h2>Retried jobs</h2>
    <ul>
      <li>last 30 days: {diagnostics.retried_jobs_30d}</li>
      {#each Object.entries(diagnostics.k5.retried_jobs) as [band, value] (band)}
        <li>{band}: {value}</li>
      {/each}
    </ul>
  </section>

  <section aria-label="Jobs by terminal state">
    <h2>Jobs by terminal state (last 30 days)</h2>
    <ul>
      {#each Object.entries(diagnostics.jobs_by_terminal_state_30d) as [state, value] (state)}
        <li>{state}: {value}</li>
      {/each}
    </ul>
  </section>

  <section aria-label="Variants per project and day">
    <h2>Variants per project and day</h2>
    <ul>
      <li>median: {figure(diagnostics.k7.runs_per_project_day.median)}</li>
      <li>max: {figure(diagnostics.k7.runs_per_project_day.max)}</li>
    </ul>
  </section>
{:catch error}
  <p role="alert">{failureText(error)}</p>
{/await}

<style>
  h2 {
    margin: var(--space-4) 0 var(--space-1);
  }
  ul {
    margin: 0;
    padding-left: var(--space-6);
  }
  section {
    overflow-x: auto; /* a wide line scrolls in its own box, never the page */
  }
  .meta {
    color: var(--color-text-muted);
  }
  .alarm {
    font-weight: 600;
  }
</style>
