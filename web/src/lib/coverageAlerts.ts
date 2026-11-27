/** The ids that lie outside the loaded map now and did not before: each item is warned about once, when it becomes
 * outside (a click on the map, typed coordinates, a file import), and not again while it stays outside. */
export function newlyOutside(previous: string[], now: string[]): string[] {
  return now.filter((id) => !previous.includes(id));
}

/** The alert for one item that is outside the map, in the approved words (D300); `where` names the loaded regions. */
export function alertTextOutside(name: string, where: string): string {
  return `${name} is outside the planner's road map (${where}). It is kept, but it can't be planned unless its region is added on the Road map screen`;
}
