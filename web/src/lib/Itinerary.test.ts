// The stops of a plan run, in order (slice 01b): name and road leg; a track also shows its entry and exit (HC-1), as
// coordinates by decision D202.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, step 04-10); the assembled itinerary is property-tested
// at the domain level (step 04-02).
import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Itinerary from './Itinerary.svelte';
import type { PlanStop } from './api';

const casa: PlanStop = {
  name: 'Casa Marco, Torino',
  type: 'poi',
  leg_km: null,
  entry: null,
  exit: null,
};
const assietta: PlanStop = {
  name: "Strada dell'Assietta",
  type: 'track',
  leg_km: 52.06,
  entry: { lat: 45.056, lon: 7.041 },
  exit: { lat: 44.958, lon: 6.879 },
};
const briancon: PlanStop = { ...casa, name: 'Briancon', leg_km: 12.25 };
const home: PlanStop = { ...casa, leg_km: 108.4 };

function rows(): string[] {
  return within(screen.getByRole('list', { name: 'Itinerary' }))
    .getAllByRole('listitem')
    .map((row) => row.textContent ?? '');
}

describe('Itinerary', () => {
  it('lists every stop in order with its road leg, the first stop having none', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon, home] } });

    const [first, second, third, fourth, ...others] = rows();
    expect(others).toEqual([]);
    expect(first).toContain('Casa Marco, Torino');
    expect(first).not.toContain('km');
    expect(second).toContain("Strada dell'Assietta");
    expect(second).toContain('52.1 km');
    expect(third).toContain('Briancon');
    expect(third).toContain('12.2 km');
    expect(fourth).toContain('Casa Marco, Torino');
    expect(fourth).toContain('108.4 km');
  });

  it('shows a track as entry -> exit in coordinates, and a place without any', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon] } });

    const [first, second, third] = rows();
    expect(second).toContain('45.0560, 7.0410 -> 44.9580, 6.8790');
    expect(first).not.toContain('->');
    expect(third).not.toContain('->');
  });
});
