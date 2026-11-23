// The phase the page shows (D283), one at a time, from what the page knows. Pure, so that the rules are tested without a DOM.
export type TripPhase = 'loading' | 'build' | 'planning' | 'route';

export interface TripFacts {
  /** The run list is being read for the first time. */
  loading: boolean;
  /** A job of this page is active. */
  jobActive: boolean;
  /** A ready route is on show. */
  readyRun: boolean;
  /** Marco pressed Edit trip and has not planned since. */
  editing: boolean;
}

/** While the runs are first read (and no job is active) nothing is known: Loading, so that Build the trip does not flash. A job of the page wins; then a ready route not being edited (also under a later failure); else building. */
export function tripPhase(facts: TripFacts): TripPhase {
  if (facts.jobActive) return 'planning';
  if (facts.loading) return 'loading';
  if (facts.readyRun && !facts.editing) return 'route';
  return 'build';
}
