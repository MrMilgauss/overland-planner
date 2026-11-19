// The phase the page shows (D283): one of Build the trip, Planning, Your route, from what the page knows. A table over
// every transition; the pure function has no DOM.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); the table pins every D283 transition by example.
import { describe, expect, it } from 'vitest';
import { tripPhase, type TripFacts, type TripPhase } from './tripPhase';

const NONE: TripFacts = {
  loading: false,
  jobActive: false,
  readyRun: false,
  editing: false,
  failedLatest: false,
};

const TRANSITIONS: [string, Partial<TripFacts>, TripPhase][] = [
  ['no ready run', {}, 'build'],
  ['the runs being read', { loading: true }, 'build'],
  ['a job of the page active', { jobActive: true }, 'planning'],
  [
    'a job active, whatever else holds',
    { jobActive: true, readyRun: true, editing: true, failedLatest: true },
    'planning',
  ],
  ['a ready run, not editing', { readyRun: true }, 'route'],
  ['Edit trip pressed on a ready run', { readyRun: true, editing: true }, 'build'],
  [
    'a failed latest run with a ready route on show',
    { readyRun: true, failedLatest: true },
    'route',
  ],
  [
    'a failed, cancelled, timed-out or refused plan without a ready route',
    { failedLatest: true },
    'build',
  ],
];

describe('tripPhase', () => {
  it.each(TRANSITIONS)('picks the phase for %s', (_facts, facts, phase) => {
    expect(tripPhase({ ...NONE, ...facts })).toBe(phase);
  });
});
