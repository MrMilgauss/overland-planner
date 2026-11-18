// WCAG 2.x contrast for the browser checks: relative luminance, ratio, and the page-side readers that find the colour a
// piece of text (or a focus ring) really sits on, by walking up to the first opaque ancestor.
import type { Page } from '@playwright/test';

export type Rgb = [number, number, number];

// "#rrggbb", "#rgb", "rgb(r, g, b)" or "rgba(r, g, b, a)" (what getComputedStyle answers); anything else is an error.
export function parseColour(text: string): Rgb {
  const value = text.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value); // the build may shorten #ffffff to #fff
  if (hex) {
    const full = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join('') : hex[1];
    const n = parseInt(full, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgb = /^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(value);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  throw new Error(`not a colour the contrast check reads: "${text}"`);
}

function luminance([r, g, b]: Rgb): number {
  const [lr, lg, lb] = [r, g, b].map((channel) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(parseColour(a)), luminance(parseColour(b))].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export type TextColours = { text: string; colour: string; background: string };
export type FocusLook = {
  element: string;
  outlineStyle: string;
  outlineWidth: number;
  outlineColour: string;
  background: string;
};

// Runs in the page (serialised): `text` reads every visible text node's colour and effective background (the map's own
// overlays and the browser's select options excluded); `focus` reads the focused element's outline and the page colour.
export async function readColours(page: Page, mode: 'text'): Promise<TextColours[]>;
export async function readColours(page: Page, mode: 'focus'): Promise<FocusLook>;
export async function readColours(page: Page, mode: 'text' | 'focus'): Promise<TextColours[] | FocusLook> {
  return page.evaluate((what) => {
    const opaque = (colour: string): boolean => {
      const m = /^rgba?\(([^)]*)\)$/.exec(colour);
      if (!m) return false;
      const parts = m[1].split(/[,/\s]+/).filter(Boolean);
      return parts.length < 4 || Number(parts[3]) === 1;
    };
    const effectiveBackground = (start: Element | null): string => {
      for (let el = start; el; el = el.parentElement) {
        const colour = getComputedStyle(el).backgroundColor;
        if (opaque(colour)) return colour;
      }
      return 'rgb(255, 255, 255)'; // the canvas
    };
    if (what === 'focus') {
      const el = document.activeElement as HTMLElement;
      const style = getComputedStyle(el);
      return {
        element: `${el.tagName.toLowerCase()} "${(el.innerText || el.getAttribute('aria-label') || '').trim()}"`,
        outlineStyle: style.outlineStyle,
        outlineWidth: parseFloat(style.outlineWidth),
        outlineColour: style.outlineColor,
        background: effectiveBackground(document.body),
      };
    }
    const found: { text: string; colour: string; background: string }[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = (node.textContent ?? '').trim();
      const el = node.parentElement;
      if (!text || !el) continue;
      if (el.closest('select, option, script, style, .maplibregl-map, .run-marker')) continue;
      const box = el.getBoundingClientRect();
      if (!el.checkVisibility() || box.width === 0 || box.height === 0) continue;
      found.push({
        text,
        colour: getComputedStyle(el).color,
        background: effectiveBackground(el),
      });
    }
    return found;
  }, mode);
}
