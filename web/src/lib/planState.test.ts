// The plan state picked from the panel's facts (D266): exactly one of six, in the order Loading, Planning, Failed,
// Stale, Plan run #N, No plan yet. Table-driven; the pure function has no DOM.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); the order is pinned over every combination of facts.
import { describe, expect, it } from 'vitest';
import { estimateMarker, planState, type PlanFacts, type PlanStateName } from './planState';

const NONE: PlanFacts = {
  loading: false,
  planning: false,
  failed: false,
  stale: false,
  readyRunNumber: undefined,
};

const SIX: [string, Partial<PlanFacts>, PlanStateName, string][] = [
  ['runs being read', { loading: true }, 'loading', 'Loading'],
  ['a job running', { planning: true }, 'planning', 'Planning'],
  ['the latest run Failed', { failed: true }, 'failed', 'Failed'],
  ['the shown ready run Stale', { stale: true, readyRunNumber: 4 }, 'stale', 'Stale'],
  ['a ready run', { readyRunNumber: 6 }, 'success', 'Plan run #6'],
  ['none', {}, 'empty', 'No plan yet'],
];

describe('planState', () => {
  it.each(SIX)('picks the state for %s', (_facts, facts, state, label) => {
    const picked = planState({ ...NONE, ...facts });
    expect(picked.state).toBe(state);
    expect(picked.label).toBe(label);
  });

  it('lets the earlier state win in every overlapping pair', () => {
    const all: PlanFacts = {
      loading: true,
      planning: true,
      failed: true,
      stale: true,
      readyRunNumber: 4,
    };
    const dropping: (keyof PlanFacts)[] = ['loading', 'planning', 'failed', 'stale'];
    const order: PlanStateName[] = ['loading', 'planning', 'failed', 'stale', 'success'];
    let facts = all;
    for (const [index, state] of order.entries()) {
      expect(planState(facts).state).toBe(state);
      if (index < dropping.length) facts = { ...facts, [dropping[index]]: false };
      else facts = { ...facts, readyRunNumber: undefined };
    }
    expect(planState(facts).state).toBe('empty');
  });

  it('gives no two states the same role, fill and glyph together', () => {
    const looks = SIX.map(([, facts]) => planState({ ...NONE, ...facts })).map(
      ({ role, fill, glyph }) => JSON.stringify({ role, fill, glyph }),
    );
    expect(new Set(looks).size).toBe(6);
  });

  it('gives each state its role, fill and glyph of the D266 table', () => {
    const table = Object.fromEntries(
      SIX.map(([, facts, state]) => {
        const { role, fill, glyph } = planState({ ...NONE, ...facts });
        return [state, `${role} ${fill} ${glyph ?? '-'}`];
      }),
    );
    expect(table).toEqual({
      loading: 'info outline -',
      planning: 'info filled -',
      failed: 'danger filled ✕',
      stale: 'warning filled !',
      success: 'success filled ✓',
      empty: 'neutral dashed -',
    });
  });
});

describe('estimateMarker', () => {
  it('is a warning pill with the approx glyph and the road-legs note for an estimate only', () => {
    expect(estimateMarker(true)).toEqual({
      label: 'estimate',
      note: 'estimate: road legs are straight-line guesses, not real roads',
      role: 'warning',
      fill: 'dashed',
      glyph: '\u2248',
    });
    expect(estimateMarker(false)).toBeUndefined();
    expect(estimateMarker(undefined)).toBeUndefined();
  });
});
