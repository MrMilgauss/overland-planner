const STORAGE_SLOT = 'map.terrain';
const ON = '1';
const OFF = '0';

/** Whether this browser last chose the Terrain map over the light base map (D287); storage may refuse, then the light base map. */
export class TerrainChoice {
  /** Resolved inside each try: in a browser with storage blocked, merely reading `window.localStorage` throws. */
  constructor(private readonly storage: () => Storage = () => window.localStorage) {}

  terrain(): boolean {
    try {
      return this.storage().getItem(STORAGE_SLOT) === ON;
    } catch {
      return false;
    }
  }

  choose(terrain: boolean): void {
    try {
      this.storage().setItem(STORAGE_SLOT, terrain ? ON : OFF);
    } catch {
      // The browser refuses to keep it: the next visit opens on the light base map.
    }
  }
}
