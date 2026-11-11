// The stops of a plan run, in order (slices 01b and 02, FR-6.1): name, type, road leg in km and time, cumulative km and
// time; a track also shows its entry and exit (HC-1, as coordinates by D202), its length and off-road time. The Totals
// (FR-6.2) show road, off-road and total km and time.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11); the itinerary and totals are
// property-tested at the domain level (steps 04-02, 05-05, 05-06, 05-07).
import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Itinerary from './Itinerary.svelte';
import type { PlanStop, PlanTotals } from './api';

const casa: PlanStop = {
  name: 'Casa Marco, Torino',
  type: 'poi',
  leg_km: null,
  leg_s: null,
  cumulative_km: null,
  cumulative_s: null,
  track_km: null,
  offroad_s: null,
  entry: null,
  exit: null,
};
const assietta: PlanStop = {
  name: "Strada dell'Assietta",
  type: 'track',
  leg_km: 52.06,
  leg_s: 3_900,
  cumulative_km: 86.05,
  cumulative_s: 8_208,
  track_km: 33.99,
  offroad_s: 4_308,
  entry: { lat: 45.056, lon: 7.041 },
  exit: { lat: 44.958, lon: 6.879 },
};
const briancon: PlanStop = {
  ...casa,
  name: 'Briancon',
  leg_km: 12.25,
  leg_s: 90,
  cumulative_km: 98.3,
  cumulative_s: 8_298,
};
const home: PlanStop = {
  ...casa,
  leg_km: 108.4,
  leg_s: 7_200,
  cumulative_km: 206.7,
  cumulative_s: 15_498,
};
/** A stop stored before the per-stop columns existed (05-07): only its road leg. */
const oldStop: PlanStop = { ...casa, name: 'Briancon', leg_km: 12.25 };
const totals: PlanTotals = {
  road_km: 412.25,
  road_s: 34_800,
  offroad_km: 98.75,
  offroad_s: 29_400,
  total_km: 511.0,
  total_s: 64_200,
};

const retrace: PlanStop = {
  name: "Retrace Strada dell'Assietta",
  type: 'retrace',
  leg_km: null,
  leg_s: null,
  cumulative_km: 120.04,
  cumulative_s: 12_516,
  track_km: 33.99,
  offroad_s: 4_308,
  entry: { lat: 44.958, lon: 6.879 },
  exit: { lat: 45.056, lon: 7.041 },
  confidence: 'unconfirmed',
  reason: 'retraces the trail backwards; check it is drivable in reverse',
};
const unconfirmedLeg: PlanStop = {
  ...briancon,
  leg_confidence: 'unconfirmed',
  leg_reason: 'entry is 1.2 km from the nearest road - check on the ground',
};
const confirmedLeg: PlanStop = { ...briancon, leg_confidence: 'confirmed', leg_reason: null };

function rows(): string[] {
  return within(screen.getByRole('list', { name: 'Itinerary' }))
    .getAllByRole('listitem')
    .map((row) => row.textContent ?? '');
}

describe('Itinerary', () => {
  it('lists every stop in order with its road leg, the first stop having none', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon, home], totals } });

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

  it('shows each stop its type, leg time and cumulative km and time, a track also its length and off-road time', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon], totals } });

    const [first, second, third] = rows();
    expect(first).toContain('Place');
    expect(second).toContain('Track');
    expect(second).toContain('Road 52.1 km, 1h05');
    expect(second).toContain('Track 34.0 km, 1h12 off-road');
    expect(second).toContain('Cumulative 86.0 km, 2h17');
    expect(third).toContain('Place');
    expect(third).toContain('Road 12.2 km, 0h02');
    expect(third).toContain('Cumulative 98.3 km, 2h18');
    expect(third).not.toContain('off-road');
  });

  it('shows a track as entry -> exit in coordinates, and a place without any', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon], totals } });

    const [first, second, third] = rows();
    expect(second).toContain('45.0560, 7.0410 -> 44.9580, 6.8790');
    expect(first).not.toContain('->');
    expect(third).not.toContain('->');
  });

  it('shows the totals: road, off-road and total km to one decimal and time in hours and minutes', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon], totals } });

    const shown = screen.getByLabelText('Totals');
    expect(shown).toHaveTextContent('Road 412.2 km, 9h40');
    expect(shown).toHaveTextContent('Off-road 98.8 km, 8h10');
    expect(shown).toHaveTextContent('Total 511.0 km, 17h50');
  });

  it('still shows a run stored before the totals and per-stop columns, with only its road legs', () => {
    render(Itinerary, { props: { stops: [casa, oldStop], totals: null } });

    const [first, second] = rows();
    expect(first).toContain('Casa Marco, Torino');
    expect(second).toContain('Road 12.2 km');
    expect(second).not.toContain('Cumulative');
    expect(second).not.toContain('h');
    expect(screen.queryByLabelText('Totals')).not.toBeInTheDocument();
  });

  // bypass: no Hypothesis in the web stack; one case per row type and leg confidence (slice 03b, step 07-09).
  it('shows a retrace with its name, the label Retrace, its reason and its km and time off-road, no Track or Road line', () => {
    render(Itinerary, { props: { stops: [casa, assietta, retrace, briancon], totals } });

    const third = rows()[2];
    expect(third).toContain("Retrace Strada dell'Assietta");
    expect(third).toContain('Retrace');
    expect(third).toContain('Unconfirmed');
    expect(third).toContain('retraces the trail backwards; check it is drivable in reverse');
    expect(third).toContain('34.0 km, 1h12 off-road');
    expect(third).not.toContain('Track');
    expect(third).not.toContain('Road');
    expect(third).not.toContain('Place');
  });

  it('marks a stop reached by an Unconfirmed road leg with its reason and leaves a Confirmed or an old one as before', () => {
    render(Itinerary, { props: { stops: [casa, unconfirmedLeg, confirmedLeg, briancon] } });

    const [, unconfirmed, confirmed, old] = rows();
    expect(unconfirmed).toContain('Unconfirmed');
    expect(unconfirmed).toContain('entry is 1.2 km from the nearest road - check on the ground');
    expect(unconfirmed).toContain('Road 12.2 km, 0h02');
    expect(confirmed).not.toContain('Unconfirmed');
    expect(old).not.toContain('Unconfirmed');
  });
});
