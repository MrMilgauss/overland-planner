// The one state of the Plan group (D266), chosen from what the panel knows, in this order: Loading, Planning, Failed,
// Stale, Plan run #N, No plan yet. Pure, so that the rules are tested without a DOM.
export type PlanStateName = 'loading' | 'planning' | 'failed' | 'stale' | 'success' | 'empty';
export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
export type Fill = 'filled' | 'outline' | 'dashed';

export interface PlanFacts {
  /** The run list is being read for the first time. */
  loading: boolean;
  /** A job of this panel is running. */
  planning: boolean;
  /** The latest run Failed. */
  failed: boolean;
  /** The ready run on show is Stale. */
  stale: boolean;
  /** The number of the ready run on show, if any. */
  readyRunNumber: number | undefined;
}

export interface PlanLook {
  state: PlanStateName;
  label: string;
  /** The colour role; it is never the only cue: fill and glyph tell the states apart too. */
  role: Tone;
  fill: Fill;
  glyph: string | undefined;
}

const CHECK = '✓';
const CROSS = '✕';

export function planState(facts: PlanFacts): PlanLook {
  if (facts.loading)
    return { state: 'loading', label: 'Loading', role: 'info', fill: 'outline', glyph: undefined };
  if (facts.planning)
    return { state: 'planning', label: 'Planning', role: 'info', fill: 'filled', glyph: undefined };
  if (facts.failed)
    return { state: 'failed', label: 'Failed', role: 'danger', fill: 'filled', glyph: CROSS };
  if (facts.stale)
    return { state: 'stale', label: 'Stale', role: 'warning', fill: 'filled', glyph: '!' };
  if (facts.readyRunNumber !== undefined) {
    const label = `Plan run #${facts.readyRunNumber}`;
    return { state: 'success', label, role: 'success', fill: 'filled', glyph: CHECK };
  }
  return {
    state: 'empty',
    label: 'No plan yet',
    role: 'neutral',
    fill: 'dashed',
    glyph: undefined,
  };
}
