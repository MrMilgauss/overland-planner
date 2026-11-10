<script lang="ts">
  // The plan of a project: Calculate, the running job's state (polled every 500 ms), then the latest ready run with
  // its Itinerary, Totals and Export GPX. Every refusal shows the planner's own message, verbatim.
  //
  // Export GPX is not offered while a job of this panel is active; the earlier run stays on show meanwhile, and its link
  // returns when the job ends without a new ready run (D208). The limit: the panel knows only the job it started, so after
  // a page reload during a job it offers the latest ready run's export, since nothing on the page says a job runs.
  //
  // While the job is stoppable (ADR-015) 'Stop and use best so far' is offered, and posted once per job; polling then
  // shows how the job ended. The run's messages (run time, label, reuse, a Failed run's failure) and the job's notices
  // are the planner's lines, shown verbatim: the web composes no wording (D211, D223 b), but for a Failed run stored
  // before its messages, which names its reason. A reused plan (memo_hit) offers Re-optimise.
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
    stopPlanJob,
    type PlanJob,
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
  let stoppable = $state(false);
  let stopPressed = $state(false);
  let notices = $state<string[]>([]);
  let endedWithoutRun = $state(''); // a job stopped before the solve: what it did, not a problem

  let nextPoll: ReturnType<typeof setTimeout> | undefined;
  let gone = false;

  const calculating = $derived(pressing || (watchedJobId !== undefined && pollProblem === ''));
  const jobActive = $derived(pressing || watchedJobId !== undefined); // through a lost connection too: it may still run

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

  /** The report's reason in product words (D211); the code only for a run stored without a report. Only for a Failed
   * run stored without its messages: one with them shows the planner's words verbatim. */
  function failedReason(run: PlanRunDetail): string {
    const reason = run.report?.reason ?? run.failure_reason;
    return reason ? ` (${reason})` : '';
  }

  function stopWatching(): void {
    clearTimeout(nextPoll);
    watchedJobId = undefined;
    pollProblem = '';
    stoppable = false;
  }

  function pollSoon(jobId: string): void {
    nextPoll = setTimeout(() => void poll(jobId), POLL_MS);
  }

  function watch(jobId: string): void {
    stopWatching();
    if (gone) return;
    watchedJobId = jobId;
    jobState = 'queued';
    stopPressed = false;
    pollSoon(jobId);
  }

  async function showJob(jobId: string, job: PlanJob): Promise<void> {
    pollProblem = '';
    jobState = job.state;
    stoppable = job.stoppable === true;
    if (job.notices && job.notices.length > 0) notices = job.notices;
    if (job.state === 'failed' || job.state === 'timed_out') {
      stopWatching();
      problem = job.message ?? failureText(undefined);
    } else if (job.state === 'cancelled') {
      stopWatching();
      endedWithoutRun = job.message ?? '';
    } else if (job.state === 'done') {
      await showLatestRuns(); // still watching, so that the earlier run's export does not come back meanwhile
      stopWatching();
    } else {
      pollSoon(jobId);
    }
  }

  function showPollFailure(jobId: string, error: unknown): void {
    if (error instanceof PlannerError && error.status === 404) {
      stopWatching();
      problem = failureText(error);
    } else {
      pollProblem = failureText(error);
      pollSoon(jobId);
    }
  }

  async function poll(jobId: string): Promise<void> {
    try {
      const job = await readPlanJob(jobId);
      if (jobId === watchedJobId) await showJob(jobId, job);
    } catch (error) {
      if (jobId === watchedJobId) showPollFailure(jobId, error);
    }
  }

  async function calculate(ignoreMemo = false): Promise<void> {
    pressing = true;
    problem = '';
    endedWithoutRun = '';
    notices = [];
    failedRun = undefined;
    try {
      const accepted = await startPlan(projectId, ignoreMemo);
      notices = accepted.notices ?? [];
      watch(accepted.job_id);
    } catch (error) {
      problem = failureText(error);
    }
    pressing = false;
  }

  /** Once per job: the button stays disabled after the press, and polling shows how the job ends. */
  async function stop(): Promise<void> {
    const jobId = watchedJobId;
    if (jobId === undefined || stopPressed) return;
    stopPressed = true;
    try {
      await stopPlanJob(jobId);
    } catch (error) {
      if (jobId === watchedJobId) {
        stopPressed = false;
        problem = failureText(error);
      }
    }
  }

  onMount(() => {
    void showLatestRuns();
    return () => {
      gone = true;
      stopWatching();
    };
  });
</script>

<button type="button" disabled={calculating} onclick={() => calculate()}>Calculate</button>

{#if watchedJobId && STATE_TEXTS[jobState]}
  <p role="status">{STATE_TEXTS[jobState]}</p>
{/if}
{#if watchedJobId && stoppable}
  <button type="button" disabled={stopPressed} onclick={stop}>Stop and use best so far</button>
{/if}
{#each notices as notice (notice)}
  <p class="notice">{notice}</p>
{/each}
{#if endedWithoutRun}
  <p>{endedWithoutRun}</p>
{/if}
{#if problem}
  <p role="alert">{problem}</p>
{/if}
{#if pollProblem}
  <p role="alert">{pollProblem}</p>
{/if}
{#if failedRun?.messages?.length}
  <div role="alert">
    {#each failedRun.messages as message, index (index)}
      <p>{message}</p>
    {/each}
  </div>
{:else if failedRun}
  <p role="alert">This plan run failed{failedReason(failedRun)}</p>
{/if}

{#if readyRun}
  <p class="run">Run {readyRun.number}</p>
  {#each readyRun.messages ?? [] as message, index (index)}
    <p class="message">{message}</p>
  {/each}
  {#if readyRun.memo_hit}
    <button type="button" disabled={calculating} onclick={() => calculate(true)}>
      Re-optimise (ignore previous result)
    </button>
  {/if}
  <Itinerary stops={readyRun.stops} totals={readyRun.totals} />
  {#if !jobActive}
    <a href={planRunExportUrl(readyRun.id)}>Export GPX</a>
  {/if}
{/if}

<style>
  button {
    padding: 0.5rem 1rem;
    font-size: 1rem; /* 16 px: no zoom-on-focus on the iPhone */
  }
  .run {
    font-weight: 600;
  }
  .message,
  .notice {
    margin: 0.25rem 0;
  }
  .notice {
    color: #5c3600;
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
