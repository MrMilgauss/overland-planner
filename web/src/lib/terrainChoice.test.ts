// The Terrain choice kept in the browser (D287), as k2Acknowledgement.test.ts does for the K2 banner.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); a table of stored values and of refusing storages.
import { describe, expect, it } from 'vitest';
import { TerrainChoice } from './terrainChoice';

function fakeStorage(initial: Record<string, string> = {}): Storage {
  const items = new Map(Object.entries(initial));
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => void items.delete(key),
    setItem: (key: string, value: string) => void items.set(key, value),
  };
}

const refusing = (): never => {
  throw new DOMException('refused', 'SecurityError');
};

describe('the Terrain choice kept in the browser', () => {
  it('answers what was chosen, shared by every instance on the same storage, in both directions', () => {
    const storage = fakeStorage();
    new TerrainChoice(() => storage).choose(true);
    expect(new TerrainChoice(() => storage).terrain()).toBe(true);
    new TerrainChoice(() => storage).choose(false);
    expect(new TerrainChoice(() => storage).terrain()).toBe(false);
  });

  it.each([
    ['a missing key', {}],
    ['garbage', { 'map.terrain': 'maybe' }],
    ['an empty value', { 'map.terrain': '' }],
  ])('answers the light base map for %s', (_case, initial) => {
    expect(new TerrainChoice(() => fakeStorage(initial)).terrain()).toBe(false);
  });

  it('answers the light base map when reading throws', () => {
    const storage = { ...fakeStorage(), getItem: refusing } as Storage;
    expect(new TerrainChoice(() => storage).terrain()).toBe(false);
  });

  it('swallows a failed write, and a storage that cannot even be reached', () => {
    const storage = { ...fakeStorage(), setItem: refusing } as Storage;
    expect(() => new TerrainChoice(() => storage).choose(true)).not.toThrow();
    const blocked = new TerrainChoice(refusing);
    expect(blocked.terrain()).toBe(false);
    expect(() => blocked.choose(true)).not.toThrow();
  });
});
