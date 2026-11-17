<script lang="ts">
  // GET /api/diagnostics as it comes (kpi-contracts `diagnostics_endpoint`): the stage p95s, the retried jobs, the jobs
  // by terminal state, the variants per project and day, the K2 and K3 counts, any above 0 in red, and the G4 count of
  // refusals for the routing engine, green at 0 and amber from 1. Keys are the
  // planner's own (stages, bands, states); seconds to one decimal; a figure without a job shows 'none'.
  import { failureText, readDiagnostics, type Diagnostics, type WindowCount } from './api';

  const NONE = 'none';
  const ALARM = '#b00020'; // K2 or K3 above 0: a hard rule broken, or a report that left out an item
  const AMBER = '#b26a00'; // G4 from 1: plans were refused while the routing engine was down or loading
  const GREEN = '#1b6e2d'; // G4 at 0
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

<main>
  <p><a href="#/">Projects</a></p>
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
            <li class:alarm={value > 0} style:color={value > 0 ? ALARM : undefined}>
              {label}: {value}
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
</main>

<style>
  main {
    max-width: 40rem;
    margin: 0 auto;
    padding: 1rem;
    overflow-wrap: anywhere; /* readable at 390 px: long keys and dates wrap */
  }
  h1 {
    font-size: 1.5rem;
  }
  h2 {
    font-size: 1.1rem;
    margin: 1rem 0 0.25rem;
  }
  ul {
    margin: 0;
    padding-left: 1.25rem;
  }
  li,
  a,
  p {
    font-size: 1rem;
  }
  .meta {
    color: #555;
  }
  .alarm {
    font-weight: 600;
  }
  [role='alert'] {
    color: #8a1c1c;
  }
</style>
