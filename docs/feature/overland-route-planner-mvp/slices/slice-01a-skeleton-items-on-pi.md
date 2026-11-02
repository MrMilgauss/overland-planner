# Slice 01a: Walking skeleton (a) - my trail and places on my own Pi

Priority: 1 | Stories: US-01b, US-02a, US-02c | Jobs (primary per story): J-06, J-01, J-01 | Strategy: WS-B | Revision 7 (final gate, D145): US-01a and all CI/image/deploy work moved to slices 00b and 00a

## Goal

On the planner that slice 00b deployed to his Pi (mock routing), Marco creates a project, imports one real Alpine GPX, adds POIs by coordinates and sets Start/End. He can see his trail's length and its entry and exit, and the project is still there after a restart.

## IN

- Create project (name required); project persists across restarts; a non-persistent volume is reported; start-up refusals (unwritable data folder, data from a newer version) (US-01b)
- Import ONE single-track GPX (original kept); non-GPX and no-usable-track files rejected; upload cap and hostile-file refusal (US-02a)
- Add POI by decimal degrees with range validation; set Start/End (round trip = one S/E row) (US-02c)
- The walking skeleton scenario (start, load Assietta, restart, still there)

## OUT

- CI pipeline and published image (slice 00a); compose deploy, basic auth, LAN-only, idle RAM (slice 00b, US-01a)
- Optimize, itinerary and export (slice 01b)

## Learning hypothesis

Disproves "the planner keeps Marco's trip data on the Pi" if a project or track is lost on restart, or if a bad file damages the project.

## Acceptance criteria (each traces to a scenario in `tests/acceptance/overland_route_planner_mvp/`)

- [ ] Walking skeleton: "Marco starts his planner, loads his Assietta trail and still finds it after a restart"
- [ ] US-01b: "Marco creates a trip project"; "A project without a name is not created"; "A trip project survives a restart"; "Missing persistent storage is reported..." (+ 3 `@technical` start-up scenarios)
- [ ] US-02a: "Marco imports his Assietta trail"; "A file that is not GPX is rejected"; "A trail file without any usable track is rejected" (+ 2 `@technical`: hostile file, upload cap)
- [ ] US-02c: "Marco adds Briancon by coordinates"; "Coordinates out of range are rejected..."; "Coordinates on the edge of the valid range are accepted"; "Home is both Start and End of a round trip"; "A one-way trip has a different Start and End"

## Production-like data

Marco's real `assietta.gpx` (Strada dell'Assietta, Pian dell'Alpe -> Sestriere, ~34.2 km); POIs Casa Marco, Torino (45.0703, 7.6869), Briancon (44.8990, 6.6430), Aosta (45.7370, 7.3200).

## Dogfood moment and demo DoD

Marco loads the Assietta on his own Pi, restarts the planner and finds it still there. **Precondition of the demo (D158, DEMO-1):** Marco's real `assietta.gpx` replaces the synthetic DISTILL stand-in (D112, UI-14) in the fixtures before the demo; the demo is not done on the synthetic file.

## Dependencies

Slice 00b (planner deployed on the Pi) and 00a (CI). OD#4 resolved: Svelte 5 + MapLibre GL JS (DESIGN D19).

## Effort and reference class

0.85 day (US-01b 0.4 d incl. start-up refusals, US-02a 0.25 d, US-02c 0.2 d). Reference class: greenfield CRUD on real storage.

## Pre-slice spike

None.
