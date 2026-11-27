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
