# Slice 01a: Walking skeleton (a) - my trail and places on my own Pi

Priority: 1 | Stories: US-01a, US-01b, US-02a | Jobs (primary per story): J-06, J-06, J-01 | Strategy: WS-B

## Goal

Marco runs `docker compose up -d` on his Pi, opens the planner from his desktop, creates a project, imports one real Alpine GPX, adds POIs by coordinates and sets Start/End. He can see his trail's length and its entry and exit, and the project is still there after a restart.

## IN

- Compose stack for ARM64 (Pi) and amd64 (PC), serving the UI at `<pi-host>:<port>`
- Health check, structured stdout log line, optional basic auth, LAN-only by default, no secrets in the image, idle RAM < 300 MB
- Create project (name required); project persists across restarts; a non-persistent volume is reported
- Import ONE single-track GPX (original kept); invalid file rejected
- Add POI by decimal degrees with range validation
- Set Start/End (round trip = one S/E row)

## OUT

- Optimize, itinerary and export (slice 01b); everything listed under OUT in slice 01b

## Learning hypothesis

Disproves "a single compose stack runs on Marco's ARM64 Pi and keeps his data" if the image does not run on the Pi or a project is lost on restart.

## Acceptance criteria (each traces to a scenario in the .feature file)

- [ ] US-01a: "Marco brings the planner up on his Pi with one command"; "The same setup runs on Marco's PC"; "Household members are asked for the shared password..."; "The planner stays on the home network by default"; "Sharing the planner image never shares Marco's secrets"; "The idle planner leaves room on the Pi"
- [ ] US-01b: "Marco creates a trip project"; "A project without a name is not created"; "A trip project survives a restart"; "Missing persistent storage is reported..."
- [ ] US-02a: "Marco imports his Assietta trail"; "Marco adds Briancon by coordinates"; "Coordinates out of range are rejected..."; "A file that is not GPX is rejected"; "Home is both Start and End of a round trip"; "A one-way trip has a different Start and End"

## Production-like data

Real `assietta.gpx` (Strada dell'Assietta, Pian dell'Alpe -> Sestriere, ~34.2 km); POIs Casa Marco, Torino (45.0703, 7.6869), Briancon (44.8990, 6.6430), Aosta (45.7370, 7.3200).

## Dogfood moment

Marco loads the Assietta on his own Pi, restarts the stack and finds it still there; Giulia opens the planner from her phone.

## Dependencies

None. OD#4 resolved: Svelte 5 + MapLibre GL JS (DESIGN D19). OD#5 resolved: verified on Marco's Raspberry Pi 5 16 GB, `pi.example` (DESIGN D38) (U14). Revision 6 (U21): the "secrets" scenario checks the basic-auth password only, since the MVP has no routing API key; idle memory excludes the routing engine (NFR-5).

## Effort and reference class

1 day (US-01a 0.4 d, US-01b 0.3 d, US-02a 0.3 d). Reference class: greenfield CRUD + compose skeleton.

## Pre-slice spike

None.
