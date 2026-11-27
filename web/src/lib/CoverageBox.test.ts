// The coverage box of Build the trip (US-28 S1, S6): the regions the roads are loaded for and the map date, or
// "Map coverage unknown" (with the date when there is one) and never a guessed list.
// bypass: no Hypothesis in the web stack (EXEMPT FROM PARADIGM); a closed table of the cases of known x date.
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import CoverageBox from './CoverageBox.svelte';

const EIGHT = [
  'Italy',
  'Spain',
  'Switzerland',
  'Austria',
  'Rhône-Alpes',
  "Provence-Alpes-Côte d'Azur",
  'Languedoc-Roussillon',
  'Midi-Pyrénées',
];

describe('Coverage box', () => {
  it.each([
    {
      case: 'known: the regions joined with commas and "and", and the date',
      props: { known: true, regions: EIGHT, mapDate: '2026-11-27T12:00:00Z' },
      lines: [
        "Roads loaded for: Italy, Spain, Switzerland, Austria, Rhône-Alpes, Provence-Alpes-Côte d'Azur, Languedoc-Roussillon and Midi-Pyrénées",
        'Map data: 27 November 2026',
      ],
      absent: ['Map coverage unknown'],
    },
    {
      case: 'known with one region',
      props: { known: true, regions: ['Italy'], mapDate: '2026-11-27T12:00:00Z' },
      lines: ['Roads loaded for: Italy', 'Map data: 27 November 2026'],
      absent: ['Map coverage unknown'],
    },
    {
      case: 'unknown with a date: the date is kept, no list',
      props: { known: false, regions: [], mapDate: '2026-11-26T12:00:00Z' },
      lines: ['Map coverage unknown', 'Map data: 26 November 2026'],
      absent: ['Roads loaded for'],
    },
    {
      case: 'unknown without a date',
      props: { known: false, regions: [], mapDate: null },
      lines: ['Map coverage unknown'],
      absent: ['Roads loaded for', 'Map data'],
    },
  ])('$case', ({ props, lines, absent }) => {
    render(CoverageBox, { props });

    for (const line of lines) expect(screen.getByText(line)).toBeInTheDocument();
    for (const text of absent) expect(screen.queryByText(new RegExp(text))).not.toBeInTheDocument();
  });

  it.each([
    {
      case: 'two land groups: both named, a ferry would be needed',
      groups: [{ regions: ['Italy', 'Spain'] }, { regions: ['Utah'] }],
      shown: true,
    },
    { case: 'one land group: nothing', groups: [{ regions: ['Italy', 'Spain'] }], shown: false },
    { case: 'no group: nothing', groups: [], shown: false },
  ])('$case', ({ groups, shown }) => {
    render(CoverageBox, {
      props: { known: true, regions: ['Italy', 'Spain', 'Utah'], mapDate: null, groups },
    });

    const warning = screen.queryByText(/not linked by land/);
    if (!shown) {
      expect(warning).not.toBeInTheDocument();
      return;
    }
    expect(warning).toHaveTextContent(
      'These stops are in areas not linked by land (Italy and Spain | Utah), so a trip between them would need a ferry',
    );
  });
});
