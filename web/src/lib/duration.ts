import { roundHalfEven } from './rounding';

/** A duration as `XhMM`, the text of the planner's hours_minutes: minutes are Python's round(seconds / 60), which takes
 * an exact half minute to the even minute where Math.round would go up. Seconds may be fractional (off-road time is
 * km / speed); the division is the same IEEE one on both sides, and x - floor(x) is exact, so the tie test is too. */
export function durationText(seconds: number): string {
  const minutes = roundHalfEven(seconds / 60);
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}`;
}
