// The stops of a plan run as steps (FR-6.1, D286): the stop's number as the map has it (S and E for the Start and the
// End), name, type word, road leg in km and time, a trail's length and off-road time; each step is a button that tells
// the page which stop is selected. The cumulative km and the entry and exit coordinates are in the step's title, not
// in view (D202 kept for the GPX); the totals are the route card's.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM, steps 04-10 and 05-11); the itinerary and totals are
// property-tested at the domain level (steps 04-02, 05-05, 05-06, 05-07).
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Itinerary from './Itinerary.svelte';
import type { PlanStop } from './api';

afterEach(cleanup);

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

function steps(): HTMLElement[] {
  return within(screen.getByRole('list', { name: 'Itinerary' })).getAllByRole('button');
}

function rows(): string[] {
  return steps().map((step) => step.textContent ?? '');
}

describe('Itinerary', () => {
  it('lists every stop in order as a step, numbered as the map numbers it, S and E for the ends', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon, home] } });

    const [first, second, third, fourth, ...others] = rows();
    expect(others).toEqual([]);
    expect(first).toMatch(/^S\s*Casa Marco, Torino/);
    expect(second).toMatch(/^2\s*Strada dell'Assietta/);
    expect(third).toMatch(/^3\s*Briancon/);
    expect(fourth).toMatch(/^E\s*Casa Marco, Torino/);
  });

  it('shows each step its type word, road leg, and a trail its length and off-road time', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon, home] } });

    const [first, second, third] = rows();
    expect(first).toContain('Place');
    expect(first).not.toContain('km');
    expect(second).toContain('Trail');
    expect(second).toContain('Road 52.1 km, 1h05');
    expect(second).toContain('Trail 34.0 km, 1h12 off-road');
    expect(third).toContain('Place');
    expect(third).toContain('Road 12.2 km, 0h02');
    expect(third).not.toContain('off-road');
  });

  it('keeps the cumulative km and the entry and exit out of view, in the step title', () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon, home] } });

    const [first, second] = steps();
    expect(second.textContent).not.toContain('Cumulative');
    expect(second.textContent).not.toContain('->');
    expect(second).toHaveAttribute('title', expect.stringContaining('Cumulative 86.0 km, 2h17'));
    expect(second).toHaveAttribute(
      'title',
      expect.stringContaining('45.0560, 7.0410 -> 44.9580, 6.8790'),
    );
    expect(first.getAttribute('title') ?? '').not.toContain('->');
  });

  it("shows no totals: they are the route card's", () => {
    render(Itinerary, { props: { stops: [casa, assietta, briancon, home] } });

    expect(screen.queryByLabelText('Totals')).not.toBeInTheDocument();
  });

  it('still shows a run stored before the per-stop columns, with only its road legs', () => {
    render(Itinerary, { props: { stops: [casa, oldStop, home] } });

    const [first, second] = rows();
    expect(first).toContain('Casa Marco, Torino');
    expect(second).toContain('Road 12.2 km');
    expect(second).not.toContain('h');
    expect(steps()[1].getAttribute('title') ?? '').not.toContain('Cumulative');
  });

  // bypass: no Hypothesis in the web stack; one case per row type and leg confidence (slice 03b, step 07-09).
  it("shows a retrace as Back the same way, with the planner's reason verbatim and its km and time off-road, no Trail, Road or Place", () => {
    render(Itinerary, { props: { stops: [casa, assietta, retrace, briancon] } });

    const third = rows()[2];
    expect(third).toMatch(/^3\s*Retrace Strada dell'Assietta/);
    expect(third).toContain('Back the same way');
    expect(third).toContain('Unconfirmed');
    expect(third).toContain('retraces the trail backwards; check it is drivable in reverse');
    expect(third).toContain('34.0 km, 1h12 off-road');
    expect(third).not.toContain('Trail');
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

  it('tells the page the stop number of the step pressed, and highlights the selected step only', async () => {
    const onselect = vi.fn();
    const { rerender } = render(Itinerary, {
      props: { stops: [casa, assietta, briancon], selected: undefined, onselect },
    });
    expect(steps().filter((step) => step.hasAttribute('aria-current'))).toEqual([]);

    await fireEvent.click(steps()[1]);
    expect(onselect).toHaveBeenCalledExactlyOnceWith(2);

    await rerender({ stops: [casa, assietta, briancon], selected: 2, onselect });
    expect(steps().map((step) => step.getAttribute('aria-current'))).toEqual([null, 'step', null]);
  });

  it("scrolls a step into view when the map selects it, and not when the step's own press did", async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const props = { stops: [casa, assietta, briancon], onselect: vi.fn() };
    const { rerender } = render(Itinerary, { props: { ...props, selected: undefined } });

    await fireEvent.click(steps()[1]); // pressed here: the page gives the number back
    await rerender({ ...props, selected: 2 });
    expect(scrolled).not.toHaveBeenCalled();

    await rerender({ ...props, selected: 3 }); // picked on the map
    expect(scrolled).toHaveBeenCalledExactlyOnceWith({ block: 'nearest' });
    expect(scrolled.mock.contexts[0]).toBe(steps()[2]);
  });

  it('scrolls to a step the map selects again after the selected step was pressed once more', async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const props = { stops: [casa, assietta, briancon], onselect: vi.fn() };
    const { rerender } = render(Itinerary, { props: { ...props, selected: 2 } });
    scrolled.mockClear();

    await fireEvent.click(steps()[1]); // already selected: the page gives nothing back
    await rerender({ ...props, selected: undefined }); // Show whole route on the map
    await rerender({ ...props, selected: 2 }); // the map picks that stop again

    expect(scrolled).toHaveBeenCalledExactlyOnceWith({ block: 'nearest' });
  });
});
