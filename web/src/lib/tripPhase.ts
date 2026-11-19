// The phase the page shows (D283), one at a time, from what the page knows. Pure, so that the rules are tested without a DOM.
export type TripPhase = 'build' | 'planning' | 'route';

export interface TripFacts {
  /** The run list is being read for the first time. */
  loading: boolean;
  /** A job of this page is active. */
  jobActive: boolean;
  /** A ready route is on show. */
  readyRun: boolean;
  /** Marco pressed Edit trip and has not planned since. */
  editing: boolean;
  /** The latest plan could not be made (failed, stopped, timed out or refused). */
  failedLatest: boolean;
}

/** A job of the page wins; then a ready route not being edited (also under a later failure); else building. */
export function tripPhase(facts: TripFacts): TripPhase {
  if (facts.jobActive) return 'planning';
  if (facts.readyRun && !facts.editing) return 'route';
  return 'build';
}
