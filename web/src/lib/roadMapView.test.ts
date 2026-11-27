// The words of the Road map screen (US-27): sizes in decimal GB as Geofabrik and the planner count them, the map's
// day in UTC, and the keys of the choice a pending change makes. Pure functions, table cases.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 03-10); one table per behaviour.
import { describe, expect, it } from 'vitest';
import {
  estimateText,
  mapDateText,
  keepsPolling,
  pausedLine,
  pendingKeys,
  plannedText,
  remainingText,
  resultOf,
  sizeText,
  startAtUtc,
  stepMarks,
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

  // Marco is in Milan (Europe/Rome, UTC+1 in winter); it is Friday 27 November 21:00 there unless said otherwise.
  const EVENING = '2026-11-27T20:00:00Z';
  it.each([
    ['2026-11-27T22:30:00Z', EVENING, 60, 'Rebuild planned for tonight 23:30'],
    ['2026-11-28T01:00:00Z', EVENING, 60, 'Rebuild planned for tonight 02:00'],
    ['2026-11-28T01:00:00Z', EVENING, 0, 'Rebuild planned for tonight 02:00 (Pi time)'],
    ['2026-11-28T10:59:00Z', EVENING, 60, 'Rebuild planned for tonight 11:59'],
    ['2026-11-28T11:00:00Z', EVENING, 60, 'Rebuild planned for tomorrow 12:00'],
    ['2026-11-28T17:30:00Z', EVENING, 60, 'Rebuild planned for tomorrow 18:30'],
    ['2026-11-29T01:00:00Z', EVENING, 60, 'Rebuild planned for 02:00 on 29 November'],
    ['2026-11-27T15:00:00Z', '2026-11-27T08:00:00Z', 60, 'Rebuild planned for today 16:00'],
    ['2026-11-27T17:00:00Z', '2026-11-27T08:00:00Z', 60, 'Rebuild planned for tonight 18:00'],
  ])('words a rebuild planned at %s, seen at %s, as: %s', (startAt, seen, piOffset, words) => {
    expect(plannedText(startAt, piOffset, Date.parse(seen), 'Europe/Rome')).toBe(words);
  });

  it.each([
    [null, 0, ['current', 'next', 'next', 'next', 'next']],
    ['checking', 0, ['done', 'current', 'next', 'next', 'next']],
    ['downloading', 1, ['done', 'done', 'current', 'next', 'next']],
    ['building', 2, ['done', 'done', 'done', 'current', 'next']],
    ['switching', 3, ['done', 'done', 'done', 'done', 'current']],
  ])('ticks the steps of a rebuild at %s (%s done)', (step, stepsDone, marks) => {
    const shown = stepMarks(step, stepsDone);
    expect(shown.map((entry) => entry.label)).toEqual([
      'Waiting',
      "Checking the Pi's disk and memory",
      'Downloading',
      'Building',
      'Switching to the new map',
    ]);
    expect(shown.map((entry) => entry.mark)).toEqual(marks);
  });

  it.each([
    ['building', '2026-11-27T20:48:00Z', 'about 31 minutes left'],
    ['building', '2026-11-27T20:17:20Z', 'about 1 minute left'],
    ['building', '2026-11-27T20:00:00Z', 'about 1 minute left'],
    ['building', '2026-11-27T20:16:00Z', 'about 1 minute left'],
    ['downloading', '2026-11-27T20:48:00Z', ''],
    ['switching', '2026-11-27T20:48:00Z', ''],
    [null, '2026-11-27T20:48:00Z', ''],
    ['building', null, ''],
  ])('says the time left of the %s step with planning back at %s: "%s"', (step, back, words) => {
    expect(remainingText(step, back, Date.parse('2026-11-27T20:17:00Z'))).toBe(words);
  });

  it('keeps asking the planner only while a change is planned or running', () => {
    const states = ['none', 'planned', 'running', 'done', 'failed', 'cancelled'];
    expect(states.filter(keepsPolling)).toEqual(['planned', 'running']);
  });

  it.each([
    ['2026-11-27T21:48:00Z', 'The road map is being rebuilt; planning is back at about 22:48.'],
    [null, 'The road map is being rebuilt; planning is back when it ends.'],
  ])('says planning is paused until %s', (back, words) => {
    expect(pausedLine(back, 'Europe/Rome')).toBe(words);
  });

  const DISK =
    "The rebuild didn't finish: the Pi has 18 GB of free disk and needs 25 GB. The previous road map is back (map data 27 November 2026); nothing is lost. Your change is kept: free some space and press Rebuild road map again.";
  const MEMORY =
    "The rebuild didn't finish: the Pi has only 4 GB of memory, too little to rebuild the map. The previous road map is back; nothing is lost.";
  const POWER =
    "The rebuild didn't finish: the Pi lost power or restarted during the rebuild. The previous road map is back (map data 27 November 2026); nothing is lost. Your change is kept: press Rebuild road map again.";
  const GENERIC =
    "The rebuild didn't finish: something went wrong. The previous road map is back; nothing is lost.";
  const DONE =
    'Road map rebuilt on 28 November at 02:56. Portugal added; 9 regions, map data 28 November 2026.';
  const ended = (state: string, code: string | null, message: string) => ({
    state,
    result: { code, message, finished_at: '2026-11-28T01:56:00Z' },
  });

  it.each([
    ['done', ended('done', null, DONE), { kind: 'done', text: DONE }],
    ['failed on disk numbers', ended('failed', 'disk', DISK), { kind: 'failed', text: DISK }],
    [
      'failed on memory numbers',
      ended('failed', 'memory', MEMORY),
      { kind: 'failed', text: MEMORY },
    ],
    [
      'interrupted by a power cut',
      ended('failed', 'interrupted', POWER),
      { kind: 'failed', text: POWER },
    ],
    [
      'failed with a code unknown to the planner',
      ended('failed', null, GENERIC),
      { kind: 'failed', text: GENERIC },
    ],
    [
      'failed with no words from the planner',
      { state: 'failed' },
      {
        kind: 'failed',
        text: "The rebuild didn't finish. The previous road map is back; nothing is lost.",
      },
    ],
    ['cancelled', ended('cancelled', null, 'cancelled'), null],
    ['no change', { state: 'none' }, null],
    ['running', { state: 'running' }, null],
  ])('reads the result of a change that is %s as the planner words it', (_name, change, result) => {
    expect(resultOf(change)).toEqual(result);
  });
});
