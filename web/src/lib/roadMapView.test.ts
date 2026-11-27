// The words of the Road map screen (US-27): sizes in decimal GB as Geofabrik and the planner count them, the map's
// day in UTC, and the keys of the choice a pending change makes. Pure functions, table cases.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); one table per behaviour.
import { describe, expect, it } from 'vitest';
import { mapDateText, pendingKeys, sizeText } from './roadMapView';

describe('road map view words', () => {
  it.each([
    [2_200_000_000, '2.2 GB'],
    [6_400_000_000, '6.4 GB'],
    [400_000_000, '0.4 GB'],
    [100_000_000, '0.1 GB'],
    [10_000_000_000, '10.0 GB'],
    [50_000_000, '50 MB'],
    [10_000, '0 MB'],
    [null, 'size unknown'],
  ])('says %s bytes as %s', (bytes, words) => {
    expect(sizeText(bytes)).toBe(words);
  });

  it.each([
    ['2026-11-27T12:00:00Z', '27 November 2026'],
    ['2026-11-27T23:59:00Z', '27 November 2026'],
    ['2026-11-26T00:00:00Z', '26 November 2026'],
  ])('dates the map %s as %s, in UTC', (iso, words) => {
    expect(mapDateText(iso)).toBe(words);
  });

  it.each([
    [['italy', 'spain'], [], [], ['italy', 'spain']],
    [['italy', 'spain'], ['spain'], [], ['italy']],
    [['italy', 'spain'], [], ['us/utah'], ['italy', 'spain', 'us/utah']],
    [['italy', 'spain'], ['italy'], ['us/utah'], ['spain', 'us/utah']],
  ])('keeps %j without %j and with %j: %j', (loaded, removed, added, wanted) => {
    expect(pendingKeys(loaded, removed, added)).toEqual(wanted);
  });
});
