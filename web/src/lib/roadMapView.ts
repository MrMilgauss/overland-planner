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

/** An instant as Marco reads it, in the browser's zone: "01:00 on 28 November"; "(Pi time)" is added only when the
 * Pi's clock is on another offset than the browser's at that instant. */
export function whenText(iso: string, piOffsetMinutes: number, timeZone?: string): string {
  const moment = new Date(iso);
  const time = moment.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone,
  });
  const day = moment.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone });
  const note = offsetMinutes(moment, timeZone) === piOffsetMinutes ? '' : ' (Pi time)';
  return `${time} on ${day}${note}`;
}

/** What a "datetime-local" field holds (the browser's own time) as the UTC instant the planner is sent; null if empty. */
export function startAtUtc(typed: string): string | null {
  const moment = new Date(typed);
  return typed === '' || Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}
