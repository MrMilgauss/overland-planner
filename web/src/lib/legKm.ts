/** A road leg as `N.N km`, the text of Python's `{leg_km:.1f}`: toFixed rounds by the exact binary value too, except
 * that it rounds an exact tie up where Python goes to the even digit. Only .25 and .75 can be an exact tie, and x * 4
 * is exact where x * 10 is itself rounded (1.15 * 10 gives 11.5, yet 1.15 lies below the tie). */
export function legKmText(km: number): string {
  return `${roundedLeg(km)} km`;
}

function roundedLeg(km: number): string {
  const quarters = km * 4;
  const isExactTie = Number.isInteger(quarters) && quarters % 2 !== 0;
  if (!isExactTie) return km.toFixed(1);
  const tenthsBelow = Math.floor(km * 10);
  const evenTenths = tenthsBelow % 2 === 0 ? tenthsBelow : tenthsBelow + 1;
  return (evenTenths / 10).toFixed(1);
}
