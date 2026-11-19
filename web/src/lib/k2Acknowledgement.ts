const STORAGE_SLOT = 'k2.acknowledged';

/** The K2 count this browser has acknowledged (D271); storage may refuse, then nothing is ever acknowledged. */
export class K2Acknowledgement {
  /** Resolved inside each try: in a browser with storage blocked, merely reading `window.localStorage` throws. */
  constructor(private readonly storage: () => Storage = () => window.localStorage) {}

  acknowledged(): number {
    try {
      const stored = this.storage().getItem(STORAGE_SLOT);
      return stored !== null && /^\d+$/.test(stored) ? Number(stored) : 0;
    } catch {
      return 0;
    }
  }

  acknowledge(count: number): void {
    try {
      this.storage().setItem(STORAGE_SLOT, String(count));
    } catch {
      // The browser refuses to keep it: the banner simply stays.
    }
  }
}
