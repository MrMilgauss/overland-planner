/** The words of the Road map screen: sizes in decimal GB (as Geofabrik and the planner count them), the map's day. */

/** "2.2 GB"; under a tenth of a GB in whole MB; "size unknown" while the planner cannot say. */
export function sizeText(bytes: number | null): string {
  if (bytes === null) return 'size unknown';
  if (bytes >= 100_000_000) return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
  return `${Math.round(bytes / 1_000_000)} MB`;
}

/** The map's day as the page says it ("27 November 2026"), in UTC as the planner dates a map. */
export function mapDateText(isoDate: string): string {
  return new Date(isoDate).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

/** The keys the road map would hold: the loaded ones without those to be removed, then those to be added. */
export function pendingKeys(loaded: string[], removed: string[], added: string[]): string[] {
  return [...loaded.filter((key) => !removed.includes(key)), ...added];
}

/** "about 58 minutes in all, of which about 41 without planning": the planner's figures, only worded. */
export function estimateText(totalMinutes: number, pauseMinutes: number): string {
  const minutes = (count: number): string => `${count} minute${count === 1 ? '' : 's'}`;
  return `about ${minutes(totalMinutes)} in all, of which about ${pauseMinutes} without planning`;
}

/** The refusal of a download above the limit, with both figures. */
export function tooBigText(totalBytes: number, maxGb: number): string {
  return `The download would be ${sizeText(totalBytes)} and the limit is ${maxGb} GB.`;
}

/** The offset of a zone from UTC at an instant, in minutes ("GMT+05:30" is 330); the browser's zone when none is named. */
function offsetMinutes(moment: Date, timeZone?: string): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    timeZoneName: 'longOffset',
  }).formatToParts(moment);
  const name = parts.find((part) => part.type === 'timeZoneName')?.value ?? 'GMT';
  const match = /GMT([+-])(\d{2}):(\d{2})/.exec(name);
  if (!match) return 0;
  return (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3]));
}

/** The clock time of an instant in a zone (the browser's when none is named): "01:00". */
function clockTime(moment: Date, timeZone?: string): string {
  return moment.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone,
  });
}

/** " (Pi time)" when the Pi's clock is on another offset than the zone's at that instant, else nothing. */
function piNote(moment: Date, piOffsetMinutes: number, timeZone?: string): string {
  return offsetMinutes(moment, timeZone) === piOffsetMinutes ? '' : ' (Pi time)';
}

/** An instant as Marco reads it, in the browser's zone: "01:00 on 28 November"; "(Pi time)" is added only when the
 * Pi's clock is on another offset than the browser's at that instant. */
export function whenText(iso: string, piOffsetMinutes: number, timeZone?: string): string {
  const moment = new Date(iso);
  const day = moment.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone });
  return `${clockTime(moment, timeZone)} on ${day}${piNote(moment, piOffsetMinutes, timeZone)}`;
}

/** What a "datetime-local" field holds (the browser's own time) as the UTC instant the planner is sent; null if empty. */
export function startAtUtc(typed: string): string | null {
  const moment = new Date(typed);
  return typed === '' || Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}

const EVENING_FROM = 18; // a start from 18:00 on the same day, or before noon on the next, is "tonight"
const NOON = 12;

/** The calendar day of an instant in a zone, in days. */
function dayNumber(moment: Date | number, timeZone?: string): number {
  const day = new Date(moment).toLocaleDateString('sv-SE', { timeZone });
  return Date.parse(`${day}T00:00:00Z`) / 86_400_000;
}

/** A start in Marco's words relative to now: "tonight 02:00" (later this evening, or before noon tomorrow), "today 16:00",
 * "tomorrow 12:00"; any later day with its date ("02:00 on 29 November"). */
function startWords(moment: Date, now: number, piOffsetMinutes: number, timeZone?: string): string {
  const days = dayNumber(moment, timeZone) - dayNumber(now, timeZone);
  const time = clockTime(moment, timeZone);
  const hour = Number(time.slice(0, 2));
  const note = piNote(moment, piOffsetMinutes, timeZone);
  if ((days === 0 && hour >= EVENING_FROM) || (days === 1 && hour < NOON))
    return `tonight ${time}${note}`;
  if (days === 0) return `today ${time}${note}`;
  if (days === 1) return `tomorrow ${time}${note}`;
  return whenText(moment.toISOString(), piOffsetMinutes, timeZone);
}

/** What a change waiting for the helper says: a start now (or already due) waits for the helper's next look, within a
 * minute; a later one says when, in Marco's time ("Rebuild planned for tonight 02:00"). */
export function plannedText(
  startAt: string | null,
  piOffsetMinutes: number,
  now: number = Date.now(),
  timeZone?: string,
): string {
  if (startAt === null || Date.parse(startAt) <= now) return 'Waiting to start within a minute';
  return `Rebuild planned for ${startWords(new Date(startAt), now, piOffsetMinutes, timeZone)}`;
}

/** The planner is asked again every 10 seconds while a change is planned or running. */
export const POLL_MS = 10_000;
export const keepsPolling = (state: string): boolean => state === 'planned' || state === 'running';

export type StepMark = 'done' | 'current' | 'next';

const STEP_LABELS = [
  'Waiting',
  "Checking the Pi's disk and memory",
  'Downloading',
  'Building',
  'Switching to the new map',
];

/** The steps of a rebuild with where it is: Waiting while the helper has reported none, otherwise the step after the
 * `stepsDone` ones done (the planner counts from checking). */
export function stepMarks(
  step: string | null,
  stepsDone: number,
): { label: string; mark: StepMark }[] {
  const on = step === null ? 0 : Math.min(stepsDone + 1, STEP_LABELS.length - 1);
  return STEP_LABELS.map((label, index) => ({
    label,
    mark: index < on ? 'done' : index === on ? 'current' : 'next',
  }));
}

/** From the building step: "about 31 minutes left", counted to the planner's time of planning back (never under a
 * minute); nothing before or after it. */
export function remainingText(step: string | null, backAt: string | null, now: number): string {
  if (step !== 'building' || backAt === null) return '';
  const minutes = Math.max(1, Math.ceil((Date.parse(backAt) - now) / 60_000));
  return `about ${minutes} minute${minutes === 1 ? '' : 's'} left`;
}

/** The one line while planning is paused (D309), in the browser's time. */
export function pausedLine(backAt: string | null, timeZone?: string): string {
  const back =
    backAt === null ? 'when it ends' : `at about ${clockTime(new Date(backAt), timeZone)}`;
  return `The road map is being rebuilt; planning is back ${back}.`;
}

export interface ChangeResult {
  code: string | null;
  message: string;
  finished_at: string;
}

/** How a rebuild ended, as the page shows it: the planner's own sentence verbatim (never a code), or a plain one when
 * the planner sent none; a change that is not over, or was cancelled, has no result to show. */
export function resultOf(change: {
  state: string;
  result?: ChangeResult | null;
}): { kind: 'done' | 'failed'; text: string } | null {
  if (change.state === 'done' && change.result)
    return { kind: 'done', text: change.result.message };
  if (change.state !== 'failed') return null;
  return {
    kind: 'failed',
    text:
      change.result?.message ??
      "The rebuild didn't finish. The previous road map is back; nothing is lost.",
  };
}
