/** Python's round(value): to the nearest integer, an exact half to the even one (Math.round would go up). Exact for
 * any value whose fraction x - floor(x) is itself exact, which it always is for a double. */
export function roundHalfEven(value: number): number {
  const below = Math.floor(value);
  const fraction = value - below;
  if (fraction < 0.5) return below;
  if (fraction > 0.5) return below + 1;
  return below % 2 === 0 ? below : below + 1;
}
