// Road leg text of an itinerary row: one decimal, the same text Python's {leg_km:.1f} gives (the acceptance step reads
// it that way). An exact tie rounds to even, where toFixed alone would round it up.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 04-10); the table holds every class of value.
import { describe, expect, it } from 'vitest';
import { legKmText } from './legKm';

describe('Road leg text', () => {
  it.each([
    // exact ties: only .25 and .75 are exact in binary, and they go to the even digit
    [12.25, '12.2 km'],
    [12.75, '12.8 km'],
    [0.25, '0.2 km'],
    [0.75, '0.8 km'],
    // not ties: 1.15 and 12.35 lie below the tie in binary, 1.45 too; 8.05 lies above it
    [1.15, '1.1 km'],
    [12.35, '12.3 km'],
    [1.45, '1.4 km'],
    [8.05, '8.1 km'],
    // ordinary values
    [52.04, '52.0 km'],
    [52.06, '52.1 km'],
    [12, '12.0 km'],
    [0, '0.0 km'],
  ])('shows %d as %s', (km, text) => {
    expect(legKmText(km)).toBe(text);
  });
});
