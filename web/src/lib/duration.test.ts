// A duration as the planner shows it ("2h17"): to the nearest minute as Python's round(seconds / 60), an exact half
// minute going to the even minute (direction_steps.py hours_minutes).
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 05-11); the totals arithmetic is property-tested
// at the domain level (step 05-05).
import { describe, expect, it } from 'vitest';
import { durationText } from './duration';

describe('durationText', () => {
  it.each([
    [0, '0h00'],
    [90, '0h02'], // 1.5 min: the half goes to the even minute
    [150, '0h02'], // 2.5 min: the half goes to the even minute
    [89.9, '0h01'],
    [150.1, '0h03'],
    [34_800, '9h40'],
    [29_400, '8h10'],
    [64_200, '17h50'],
    [8_208, '2h17'],
    [3_570, '1h00'], // 59.5 min goes to 60: the hour carries
    [1_234.5678, '0h21'],
  ])('shows %s s as %s', (seconds, text) => {
    expect(durationText(seconds)).toBe(text);
  });
});
