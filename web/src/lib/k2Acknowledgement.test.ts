import { describe, expect, it } from 'vitest';
import { K2Acknowledgement } from './k2Acknowledgement';

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

describe('K2 acknowledgement kept in the browser', () => {
  it('answers what was acknowledged, shared by every instance on the same storage', () => {
    const storage = fakeStorage();
    new K2Acknowledgement(() => storage).acknowledge(3);
    expect(new K2Acknowledgement(() => storage).acknowledged()).toBe(3);
  });

  it.each([
    ['a missing key', {}],
    ['garbage', { 'k2.acknowledged': 'lots' }],
    ['a negative number', { 'k2.acknowledged': '-2' }],
    ['a fraction', { 'k2.acknowledged': '1.5' }],
  ])('answers nothing acknowledged for %s', (_case, initial) => {
    expect(new K2Acknowledgement(() => fakeStorage(initial)).acknowledged()).toBe(0);
  });

  it('answers nothing acknowledged when reading throws', () => {
    const storage = { ...fakeStorage(), getItem: refusing } as Storage;
    expect(new K2Acknowledgement(() => storage).acknowledged()).toBe(0);
  });

  it('swallows a failed write', () => {
    const storage = { ...fakeStorage(), setItem: refusing } as Storage;
    expect(() => new K2Acknowledgement(() => storage).acknowledge(1)).not.toThrow();
  });

  it('treats a storage that cannot even be reached as nothing acknowledged and a write as swallowed', () => {
    const blocked = new K2Acknowledgement(refusing);
    expect(blocked.acknowledged()).toBe(0);
    expect(() => blocked.acknowledge(2)).not.toThrow();
  });
});
