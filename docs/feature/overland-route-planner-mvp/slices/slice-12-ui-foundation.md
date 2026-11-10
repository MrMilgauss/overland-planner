# Slice 12: A planner that looks and feels like a product (UI foundation)

Priority: delivery position right after slice 09 (see D232) | Type: user-facing polish, no new planning behaviour | Added 2026-11-10 at the user's request ("the page is plain and quite ugly"; no slice covered UI polish before)

## Goal

Marco and Giulia open the planner and it reads as one coherent product: the map is the main surface, the itinerary sits beside it, every action looks like an action, and nothing on screen can be mistaken for something it is not (an estimate shown as a real route, a failed run shown as a plan). It works on a laptop, a tablet-width window and a 390 px phone.

## IN

- Layout: the map is the main surface; stops, itinerary and totals beside it (below it on a phone); items, start/end and plan controls grouped by task, not stacked as a form
- Visual system: one set of type sizes, spacing, colours, buttons, inputs and icons, applied to every existing page; light and dark themes following the system setting
- Clear states for every screen that has them: empty, loading, working (with Stop), success, Failed, Stale; the planner's own words stay as they are
- Honest labelling: a visible "estimate" marker on any plan whose road legs came from the mock provider (it never looks like a real route), and the same marker in the exported GPX name
- Usable at 390 px (phone) and tablet width; touch-sized targets
- Keyboard focus visible, text contrast readable outdoors

## OUT

- New planning behaviour, new screens or new data (those belong to their own slices)
- Offline tiles, a custom map style, branding or a logo
- Translations (UI stays in English, place names as stored)

## Learning hypothesis

Disproves "the planner is usable in the field without explanation" if Marco or Giulia, handed the page cold, cannot (a) tell what is selected, (b) start a plan and (c) say whether the route shown is real or an estimate, in under two minutes each.

## Acceptance criteria

To be written as scenarios when the slice is picked up (DISTILL). Outcome checks, not pixel checks:

- [ ] Cold-start check above passes for two people
- [ ] Every existing page uses the same visual system; no unstyled controls remain
- [ ] Every state listed under IN has a distinct, labelled appearance
- [ ] A mock-provider plan is marked as an estimate on screen and in the GPX
- [ ] No horizontal scrolling at 390 px; no overlap at tablet width

## Production-like data

Plan run #4 of "Alpi Occidentali giugno 2027", on a real road route (slice 06a) shown on the map (slice 09).

## Dogfood moment

Marco and Giulia run the cold-start check, one on the phone and one on a laptop.

## Dependencies

Slice 09 (the map), slice 06a (real road legs, so the layout is designed around a real route). Existing Svelte 5 and MapLibre stack (OD#4); no new technology expected.

## Effort and reference class

1 day, at risk: visual work has no hard acceptance gate, so the learning hypothesis is the stop rule.

## Pre-slice spike

None. A design pass (layout and visual system) happens at the start of the slice, before code.
