<script lang="ts">
  // The plan of a project, one phase at a time (D283, tripPhase): Build the trip with 'Plan the route', Planning with the
  // running job's state (polled every 500 ms) and Stop, then Your route: the latest ready run's card with its Itinerary
  // and Totals. Every refusal shows the planner's own message, verbatim.
  //
  // Export GPX is not offered while a job of this panel is active; the earlier run stays on show meanwhile, and its link
  // returns when the job ends without a new ready run (D208). The limit: the panel knows only the job it started, so after
  // a page reload during a job it offers the latest ready run's export, since nothing on the page says a job runs.
  //
  // While the job is stoppable (ADR-015) 'Stop and use best so far' is offered, and posted once per job; polling then
  // shows how the job ended. The run's messages (run time, label, reuse, a Failed run's failure) and the job's notices
  // are the planner's lines, shown verbatim: the web composes no wording (D211, D223 b), but for a Failed run stored
  // before its messages, which names its reason. A reused plan (memo_hit) offers Re-optimise.
  import { onMount, type Snippet } from 'svelte';
  import Itinerary from './Itinerary.svelte';
  import PhaseSteps from './PhaseSteps.svelte';
  import RouteCard from './RouteCard.svelte';
  import StatusBadge from './StatusBadge.svelte';
  import { planRunLabel, planState } from './planState';
  import { tripPhase } from './tripPhase';
  import { durationText } from './duration';
  import { legKmText } from './legKm';
  import {
    failureText,
    listPlanRuns,
    PlannerError,
    type Incumbent,
    type Objective,
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

  let {
    projectId,
    objective = 'distance',
    onrunshown,
    build,
    trip,
  }: {
    projectId: string;
    objective?: Objective;
    /** The ready run on show (Your route), for the page's map, and whether it is an estimate; undefined otherwise. */
    onrunshown?: (planRunId: string | undefined, estimate: boolean) => void;
    /** What Build the trip holds above its main action: the trip's list and the controls that change it. */
    build?: Snippet;
    /** What Planning shows of the trip: a read-only list, no control. */
    trip?: Snippet;
  } = $props();

  let pressing = $state(false);
  let editing = $state(false); // Edit trip pressed on a ready route and no plan accepted since
  let jobFailed = $state(false); // the last job ended without a run: failed or timed out
  let watchedJobId = $state<string | undefined>();
  let jobState = $state<PlanJobState>('queued');
  let problem = $state('');
  let pollProblem = $state(''); // the job may well still run: polling goes on
  let readyRun = $state<PlanRunDetail | undefined>();
  let readyRunStale = $state(false); // from the run list: the project changed since the run was computed
  let failedRun = $state<PlanRunDetail | undefined>();
  let stoppable = $state(false);
  let stopPressed = $state(false);
  let notices = $state<string[]>([]);
  let incumbent = $state<Incumbent | undefined>();
  let unreadable = $state(false); // the last read of the run list failed: the page does not know whether runs exist
  let firstRead = $state(true); // the run list has not been read yet: the state is Loading
  let endedWithoutRun = $state(''); // a job stopped before the solve: what it did, not a problem

  let nextPoll: ReturnType<typeof setTimeout> | undefined;
  let gone = false;

  const jobActive = $derived(pressing || watchedJobId !== undefined); // through a lost connection too: it may still run
  const previous = $derived(failedRun !== undefined || jobFailed); // a ready route is on show under a failed plan
  const phase = $derived(
    tripPhase({
      loading: firstRead,
      jobActive,
      readyRun: readyRun !== undefined,
      editing,
      failedLatest: previous,
    }),
  );
  const look = $derived(
    planState({
      loading: firstRead,
      planning: jobActive,
      failed: previous,
      stale: readyRun !== undefined && readyRunStale,
      readyRunNumber: readyRun?.number,
      unreadable,
    }),
  );
  const PHASE_NAMES = { build: 'Build the trip', planning: 'Planning', route: 'Your route' };

  function showRoute(): void {
    editing = false;
  }

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
      readyRunStale = ready?.stale === true;
      unreadable = false;
    } catch (error) {
      problem = failureText(error);
      unreadable = true;
    }
    firstRead = false;
  }

  /** A change of the trip made elsewhere on the page (a place added on the map) takes Marco back to building. */
  export function edit(): void {
    editing = true;
  }

  /** The page asks for the runs again, e.g. after a POI added on the map, so that the latest shows Stale at once. */
  export async function reload(): Promise<void> {
    await showLatestRuns();
  }

  /** The report's reason in product words (D211); the code only for a run stored without a report. Only for a Failed
   * run stored without its messages: one with them shows the planner's words verbatim. */
  function failedReason(run: PlanRunDetail): string {
    const reason = run.report?.reason ?? run.failure_reason;
    return reason ? ` (${reason})` : '';
  }

  /** The best route so far: road seconds as a duration for `time`, road metres as km for `distance`. */
  function bestSoFar(found: Incumbent): string {
    return objective === 'time' ? durationText(found.objective) : legKmText(found.objective / 1000);
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
    incumbent = job.incumbent ?? undefined;
    if (job.notices && job.notices.length > 0) notices = job.notices;
    if (job.state === 'failed' || job.state === 'timed_out') {
      stopWatching();
      jobFailed = true;
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
    jobFailed = false;
    problem = '';
    endedWithoutRun = '';
    notices = [];
    failedRun = undefined;
    incumbent = undefined;
    try {
      const accepted = await startPlan(projectId, ignoreMemo);
      notices = accepted.notices ?? [];
      editing = false;
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

  $effect(() => {
    // The route is on the map only on Your route: while the trip is built or planned the map shows the trip's items.
    if (firstRead) return; // the runs are not read yet: nothing to say, the page's map waits for it
    const shown = phase === 'route' ? readyRun : undefined;
    onrunshown?.(shown?.id, shown?.estimate === true);
  });

  onMount(() => {
    void showLatestRuns();
    return () => {
      gone = true;
      stopWatching();
    };
  });
</script>

<div class="plan">
  <PhaseSteps {phase} canShowRoute={readyRun !== undefined && !jobActive} onshowroute={showRoute} />

  <section class="phase" aria-label={PHASE_NAMES[phase]}>
    {#if phase !== 'route' && look.state !== 'unknown'}
      <StatusBadge
        tone={look.role}
        fill={look.fill}
        glyph={look.glyph}
        label={look.label}
        data-plan-state={look.state}
        aria-busy={look.state === 'loading' ? 'true' : undefined}
      />
    {/if}
    {#if phase === 'planning'}
      <div class="progress" role="progressbar" aria-label="Planning" data-testid="plan-progress">
        <span></span>
      </div>
    {/if}
    {#if phase === 'route' && previous}
      <StatusBadge
        tone={look.role}
        fill={look.fill}
        glyph={look.glyph}
        label={look.label}
        data-plan-state={look.state}
      />
    {/if}

    {#if watchedJobId && STATE_TEXTS[jobState]}
      <p role="status">{STATE_TEXTS[jobState]}</p>
    {/if}
    {#if watchedJobId && incumbent}
      <p class="best">Best so far: {bestSoFar(incumbent)}</p>
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

    {#if phase === 'build'}
      {@render build?.()}
      <div class="action">
        <button type="button" class="primary" onclick={() => calculate()}>Plan the route</button>
      </div>
    {:else if phase === 'planning'}
      {@render trip?.()}
      {#if watchedJobId && stoppable}
        <div class="action">
          <button type="button" class="danger" disabled={stopPressed} onclick={stop}
            >Stop and use best so far</button
          >
        </div>
      {/if}
    {:else if readyRun}
      <RouteCard
        run={readyRun}
        {look}
        {previous}
        exportUrl={planRunExportUrl(readyRun.id)}
        onedit={() => (editing = true)}
      />
      <p class="run">{planRunLabel(readyRun.number)}</p>
      {#if readyRun.provider_header}
        <p class="provider">{readyRun.provider_header}</p>
      {/if}
      {#each readyRun.messages ?? [] as message, index (index)}
        <p class="message">{message}</p>
      {/each}
      {#if readyRun.memo_hit}
        <button type="button" onclick={() => calculate(true)}>
          Re-optimise (ignore previous result)
        </button>
      {/if}
      <Itinerary
        stops={readyRun.stops}
        totals={readyRun.totals}
        objectiveLabel={readyRun.objective_label}
      />
    {/if}
  </section>
</div>

<style>
  .plan {
    display: grid;
    gap: var(--space-3);
    min-height: 100%;
    align-content: start;
  }
  .phase {
    display: grid;
    gap: var(--space-2);
    align-content: start;
  }
  .phase > :global(*) {
    justify-self: start;
  }
  .phase > :global(p),
  .phase > :global(div),
  .phase > :global(ul),
  .phase > :global(ol),
  .phase > :global(section) {
    justify-self: stretch;
  }
  /* The main action stays in reach: the bottom of the panel on a laptop, of the screen on a phone (D289) */
  .action {
    position: sticky;
    bottom: 0;
    z-index: 1;
    display: grid;
    padding: var(--space-3) 0 max(var(--space-3), env(safe-area-inset-bottom));
    border-top: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  p {
    margin: 0;
  }
  .progress {
    height: var(--space-1);
    overflow: hidden;
    border-radius: var(--radius-pill);
    background: var(--color-info-bg);
  }
  .progress span {
    display: block;
    width: 40%;
    height: 100%;
    background: var(--color-info-fg);
    animation: slide 1.4s ease-in-out infinite alternate;
  }
  @keyframes slide {
    to {
      transform: translateX(150%);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .progress span {
      width: 100%;
      animation: none;
    }
  }
  .run {
    font-weight: 600;
  }
  .provider :global(.badge) {
    margin-right: var(--space-2);
    vertical-align: middle;
  }
  .message,
  .provider,
  .best,
  .notice {
    margin: var(--space-1) 0;
  }
  .notice {
    color: var(--color-warning-fg);
  }
</style>
