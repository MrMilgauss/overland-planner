<script lang="ts">
  // The plan of a project: Calculate, the running job's state (polled every 500 ms), then the latest ready run with
  // its Itinerary and Export GPX. Every refusal shows the planner's own message, verbatim.
  import { onMount } from 'svelte';
  import Itinerary from './Itinerary.svelte';
  import {
    failureText,
    listPlanRuns,
    PlannerError,
    planRunExportUrl,
    readPlanJob,
    readPlanRun,
    startPlan,
    type PlanJobState,
    type PlanRun,
    type PlanRunDetail,
  } from './api';

  const POLL_MS = 500;
  const STATE_TEXTS: Partial<Record<PlanJobState, string>> = {
    queued: 'Queued',
    computing_legs: 'Computing legs',
    waiting_for_optimizer: 'Waiting for the optimizer',
    solving: 'Solving',
    finalising: 'Finalising',
  };

  let { projectId }: { projectId: string } = $props();

  let pressing = $state(false);
  let watchedJobId = $state<string | undefined>();
  let jobState = $state<PlanJobState>('queued');
  let problem = $state('');
  let pollProblem = $state(''); // the job may well still run: Calculate is usable meanwhile, and polling goes on
  let readyRun = $state<PlanRunDetail | undefined>();
  let failedRun = $state<PlanRunDetail | undefined>();

  let nextPoll: ReturnType<typeof setTimeout> | undefined;
  let gone = false;

  const calculating = $derived(pressing || (watchedJobId !== undefined && pollProblem === ''));

  function highestNumbered(runs: PlanRun[]): PlanRun | undefined {
    return runs.reduce<PlanRun | undefined>(
      (best, run) => (best === undefined || run.number > best.number ? run : best),
      undefined,
    );
  }

  /** The highest-numbered ready run stays on show under the failure of a later run. */
  async function showLatestRuns(): Promise<void> {
    try {
      const runs = await listPlanRuns(projectId);
      const latest = highestNumbered(runs);
      const ready = highestNumbered(runs.filter((run) => run.status === 'ready'));
      failedRun = latest && latest !== ready ? await readPlanRun(latest.id) : undefined;
      readyRun = ready ? await readPlanRun(ready.id) : undefined;
    } catch (error) {
      problem = failureText(error);
    }
  }

  function stopWatching(): void {
    clearTimeout(nextPoll);
    watchedJobId = undefined;
    pollProblem = '';
  }

  function pollSoon(jobId: string): void {
    nextPoll = setTimeout(() => void poll(jobId), POLL_MS);
  }

  function watch(jobId: string): void {
    stopWatching();
    if (gone) return;
    watchedJobId = jobId;
    jobState = 'queued';
    pollSoon(jobId);
  }

  async function poll(jobId: string): Promise<void> {
    try {
      const job = await readPlanJob(jobId);
      if (jobId !== watchedJobId) return;
      pollProblem = '';
      jobState = job.state;
      if (job.state === 'failed') {
        stopWatching();
        problem = job.message ?? failureText(undefined);
      } else if (job.state === 'done') {
        stopWatching();
        await showLatestRuns();
      } else {
        pollSoon(jobId);
      }
    } catch (error) {
      if (jobId !== watchedJobId) return;
      if (error instanceof PlannerError && error.status === 404) {
        stopWatching();
        problem = failureText(error);
      } else {
        pollProblem = failureText(error);
        pollSoon(jobId);
      }
    }
  }

  async function calculate(): Promise<void> {
    pressing = true;
    problem = '';
    failedRun = undefined;
    try {
      const { job_id: jobId } = await startPlan(projectId);
      watch(jobId);
    } catch (error) {
      problem = failureText(error);
    }
    pressing = false;
  }

  onMount(() => {
    void showLatestRuns();
    return () => {
      gone = true;
      stopWatching();
    };
  });
</script>

<button type="button" disabled={calculating} onclick={calculate}>Calculate</button>

{#if watchedJobId && STATE_TEXTS[jobState]}
  <p role="status">{STATE_TEXTS[jobState]}</p>
{/if}
{#if problem}
  <p role="alert">{problem}</p>
{/if}
{#if pollProblem}
  <p role="alert">{pollProblem}</p>
{/if}
{#if failedRun}
  <p role="alert">
    This plan run failed{failedRun.failure_reason ? ` (${failedRun.failure_reason})` : ''}
  </p>
{/if}

{#if readyRun}
  <p class="run">Run {readyRun.number}</p>
  <Itinerary stops={readyRun.stops} />
  <a href={planRunExportUrl(readyRun.id)}>Export GPX</a>
{/if}

<style>
  button {
    padding: 0.5rem 1rem;
    font-size: 1rem; /* 16 px: no zoom-on-focus on the iPhone */
  }
  .run {
    font-weight: 600;
  }
  a {
    display: inline-block;
    padding: 0.5rem 0;
    font-size: 1rem;
  }
  [role='alert'] {
    color: #8a1c1c;
  }
</style>
