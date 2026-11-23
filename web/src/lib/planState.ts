// The one status of the trip's plan (D266, D284 words), chosen from what the panel knows, in this order: Loading,
// Planning…, Couldn't plan, Out of date, plan again, Route ready, then No plan yet, or no status at all when the runs are
// unreadable. Pure, so that the rules are tested without a DOM.
export type PlanStateName =
  'loading' | 'planning' | 'failed' | 'stale' | 'success' | 'empty' | 'unknown';
export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
export type Fill = 'filled' | 'outline' | 'dashed';

export interface PlanFacts {
  /** The run list is being read for the first time. */
  loading: boolean;
  /** A job of this panel is running. */
  planning: boolean;
  /** The latest plan could not be made: its run Failed, or its job ended without a run. */
  failed: boolean;
  /** The ready run on show is Stale. */
  stale: boolean;
  /** The number of the ready run on show, if any. */
  readyRunNumber: number | undefined;
  /** The run list could not be read: nothing is known, so nothing is claimed (US-21). */
  unreadable: boolean;
}

export interface PlanLook {
  state: PlanStateName;
  label: string;
  /** The colour role; it is never the only cue: fill and glyph tell the states apart too. */
  role: Tone;
  fill: Fill;
  glyph: string | undefined;
}

/** The heading of the ready run on show (shown at the top of the run's Details). */
export const planRunLabel = (number: number): string => `Plan run #${number}`;

const CHECK = '✓';
const CROSS = '✕';

export function planState(facts: PlanFacts): PlanLook {
  if (facts.loading)
    return { state: 'loading', label: 'Loading', role: 'info', fill: 'outline', glyph: undefined };
  if (facts.planning)
    return {
      state: 'planning',
      label: 'Planning…',
      role: 'info',
      fill: 'filled',
      glyph: undefined,
    };
  if (facts.failed)
    return {
      state: 'failed',
      label: "Couldn't plan",
      role: 'danger',
      fill: 'filled',
      glyph: CROSS,
    };
  if (facts.stale)
    return {
      state: 'stale',
      label: 'Out of date, plan again',
      role: 'warning',
      fill: 'filled',
      glyph: '!',
    };
  if (facts.readyRunNumber !== undefined)
    return {
      state: 'success',
      label: 'Route ready',
      role: 'success',
      fill: 'filled',
      glyph: CHECK,
    };
  if (facts.unreadable)
    return { state: 'unknown', label: '', role: 'neutral', fill: 'dashed', glyph: undefined };
  return {
    state: 'empty',
    label: 'No plan yet',
    role: 'neutral',
    fill: 'dashed',
    glyph: undefined,
  };
}

/** The one word of the estimate marker, on the pill and on the map's chip. */
export const ESTIMATE_LABEL = 'Estimate';
export const ESTIMATE_NOTE = 'estimate: road legs are straight-line guesses, not real roads';

export interface EstimateMarker {
  label: string;
  /** The title and the accessible name of the pill and of the map's chip. */
  note: string;
  role: Tone;
  fill: Fill;
  glyph: string;
}

/** The marker of a run on the offline road map (D267): the browser reads `estimate` from the run detail, never the provider line. */
export function estimateMarker(estimate: boolean | undefined): EstimateMarker | undefined {
  if (estimate !== true) return undefined;
  return {
    label: ESTIMATE_LABEL,
    note: ESTIMATE_NOTE,
    role: 'warning',
    fill: 'dashed',
    glyph: '≈',
  };
}
