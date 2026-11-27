// The alert-once rule of US-28: an item is warned about when it becomes outside the loaded map, not again while it stays
// outside. bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); a closed table over previous x now.
import { describe, expect, it } from 'vitest';
import { alertTextOutside, newlyOutside } from './coverageAlerts';

describe('newlyOutside', () => {
  it.each([
    { case: 'nothing outside before or now', previous: [], now: [], fresh: [] },
    { case: 'an item became outside', previous: [], now: ['a'], fresh: ['a'] },
    { case: 'an item already outside is not warned again', previous: ['a'], now: ['a'], fresh: [] },
    { case: 'a new one beside an old one', previous: ['a'], now: ['a', 'b'], fresh: ['b'] },
    {
      case: 'a file import of several: one each, in order',
      previous: [],
      now: ['a', 'b', 'c'],
      fresh: ['a', 'b', 'c'],
    },
    {
      case: 'an item back inside, then outside again, is warned again',
      previous: [],
      now: ['a'],
      fresh: ['a'],
    },
    { case: 'an item no longer outside is not fresh', previous: ['a'], now: [], fresh: [] },
  ])('$case', ({ previous, now, fresh }) => {
    expect(newlyOutside(previous, now)).toEqual(fresh);
  });
});

describe('alertTextOutside', () => {
  it('names the item and the loaded regions in the approved words', () => {
    expect(alertTextOutside('Lagos', 'Italy and Spain')).toBe(
      "Lagos is outside the planner's road map (Italy and Spain). It is kept, but it can't be planned unless its region is added on the Road map screen",
    );
  });
});
