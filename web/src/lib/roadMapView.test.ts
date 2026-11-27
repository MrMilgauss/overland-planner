// The words of the Road map screen (US-27): sizes in decimal GB as Geofabrik and the planner count them, the map's
// day in UTC, and the keys of the choice a pending change makes. Pure functions, table cases.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); one table per behaviour.
import { describe, expect, it } from 'vitest';
import {
  estimateText,
  mapDateText,
  pendingKeys,
  plannedText,
  sizeText,
  startAtUtc,
  tooBigText,
  whenText,
} from './roadMapView';

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

  it.each([
    [58, 41, 'about 58 minutes in all, of which about 41 without planning'],
    [55, 38, 'about 55 minutes in all, of which about 38 without planning'],
    [1, 1, 'about 1 minute in all, of which about 1 without planning'],
  ])('words the estimate %s and %s minutes', (total, pause, words) => {
    expect(estimateText(total, pause)).toBe(words);
  });

  it.each([
    [20_800_000_000, 8, 'The download would be 20.8 GB and the limit is 8 GB.'],
    [8_100_000_000, 8, 'The download would be 8.1 GB and the limit is 8 GB.'],
    [9_000_000_000, 7.5, 'The download would be 9.0 GB and the limit is 7.5 GB.'],
  ])('refuses %s bytes over %s GB in words', (bytes, limit, words) => {
    expect(tooBigText(bytes, limit)).toBe(words);
  });

  // The instant is read in the browser's zone; "(Pi time)" only when that zone's offset differs from the Pi's.
  it.each([
    ['2026-11-28T00:00:00Z', 'Europe/Rome', 60, '01:00 on 28 November'],
    ['2026-11-28T00:00:00Z', 'Europe/Rome', 0, '01:00 on 28 November (Pi time)'],
    ['2026-11-28T00:00:00Z', 'UTC', 0, '00:00 on 28 November'],
    ['2026-11-28T00:00:00Z', 'America/New_York', -300, '19:00 on 27 November'],
    ['2026-11-28T00:00:00Z', 'America/New_York', 60, '19:00 on 27 November (Pi time)'],
    ['2026-11-28T00:00:00Z', 'Asia/Kolkata', 330, '05:30 on 28 November'],
    ['2026-07-01T00:00:00Z', 'Europe/Rome', 60, '02:00 on 1 July (Pi time)'],
    ['2026-07-01T00:00:00Z', 'Europe/Rome', 120, '02:00 on 1 July'],
  ])('says %s in %s against a Pi at %s minutes as %s', (iso, zone, piOffset, words) => {
    expect(whenText(iso, piOffset, zone)).toBe(words);
  });

  it.each([
    ['Europe/Rome', '2026-11-28T02:00', '2026-11-28T01:00:00.000Z'],
    ['America/New_York', '2026-11-28T02:00', '2026-11-28T07:00:00.000Z'],
    ['Europe/Rome', '', null],
  ])('reads a start typed in %s as %s: %s UTC', (zone, typed, utc) => {
    const before = process.env.TZ;
    process.env.TZ = zone;
    try {
      expect(startAtUtc(typed)).toBe(utc);
    } finally {
      if (before === undefined) delete process.env.TZ;
      else process.env.TZ = before;
    }
  });

  it.each([
    [null, 'Waiting to start within a minute'],
    ['2026-11-27T12:00:00Z', 'Waiting to start within a minute'],
    ['2026-12-02T01:00:00Z', 'Rebuild planned for 02:00 on 2 December'],
  ])('says a rebuild planned at %s as %s', (startAt, words) => {
    const now = Date.parse('2026-11-27T13:00:00Z');
    expect(plannedText(startAt, 60, now, 'Europe/Rome')).toBe(words);
  });
});
