// D265: components use the tokens of app.css only. No hex colour in a .svelte file, except the map overlays of
// RunMap (its line colours and markers stay one light palette on the light tiles). app.css holds both themes.
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = path.resolve(__dirname, '..');
const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const MAP_OVERLAY_RULE = /[^{}]*\.run-marker[^{}]*\{[^}]*\}/g;

function svelteFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return svelteFiles(full);
    return entry.name.endsWith('.svelte') ? [full] : [];
  });
}

describe('app.css tokens', () => {
  it('leaves no hex colour in a component but the map overlays', () => {
    const offenders = svelteFiles(SRC).flatMap((file) => {
      const text = readFileSync(file, 'utf8').replace(MAP_OVERLAY_RULE, '');
      return (text.match(HEX) ?? []).map((hex) => `${path.relative(SRC, file)}: ${hex}`);
    });
    expect(offenders).toEqual([]);
  });

  it('defines every colour role in the light look and again in the dark look', () => {
    const css = readFileSync(path.join(SRC, 'app.css'), 'utf8');
    const [light, dark] = css.split('@media (prefers-color-scheme: dark)');
    const roles = [
      'bg',
      'surface',
      'text',
      'text-muted',
      'border',
      'accent',
      'on-accent',
      'focus',
    ].concat(['info', 'success', 'warning', 'danger'].flatMap((r) => [`${r}-fg`, `${r}-bg`]));
    const missing = roles.flatMap((role) =>
      [light, dark ?? ''].map((block, i) =>
        new RegExp(`--color-${role}:\\s*#[0-9a-f]{6}`, 'i').test(block ?? '')
          ? ''
          : `${i ? 'dark' : 'light'} --color-${role}`,
      ),
    );
    expect(missing.filter(Boolean)).toEqual([]);
  });
});
