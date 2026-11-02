# Slice 06a-ops (enabler): Valhalla serving on the Pi

Priority: 8a | Type: enabler (no user story; D145, OD-1) | Enables: US-10a (live scenarios S1, S7), US-06a S1b, the live routing contract check | job_id: infrastructure-only | infrastructure_rationale: real-road planning (slice 06a) needs a routing engine serving the Western Alps on the Pi; this slice runs it, seeds its map data and gives the tools to check it

## Goal

Valhalla runs in Marco's compose stack on the Pi with the map data from SPIKE-2R, within its resource caps, never published on the network, and can be checked live and measured end to end from the Mac.

## IN (DEVOPS D81-D83, D92, D95, D96, D100; OD-9)

- `valhalla` service on the internal routing network, caps `cpus 2`, `server_threads 2`, 4 GB; healthcheck on `/status`; `routing.env` with `VALHALLA_TILESET` written only by the tile tools (F-07)
- `make tiles-seed`: copy the SPIKE-2R tileset into `tilesets/20261101/`; `make spike-cleanup` deletes `~/valhalla-spike` only after a sha256 match and at a start time Marco names
- `valhalla-build` profile and `make tiles-refresh` (quarterly; build `cpus 3` with serving stopped)
- `valhalla-tunnel` + `make contract-live`; `make acceptance-pi`; `make perf-pi` end-to-end mode (slowest of 10 <= 180 s, every cold run counts, D147)

## OUT

- The planner's Valhalla adapter, objective setting and engine-down messages (slice 06a)

## Done when

- Production `valhalla` is healthy on the seeded tileset and `make contract-live` passes
- Household services keep their memory headroom during serving (checked with `make diag`)

## Demo

Shown with slice 06a (Marco compares mock and Valhalla road km).

## Dependencies

SPIKE-2R (done); slice 00b (compose on the Pi). DEVOPS pre-requisite 6; the user names the start time for the seed check and the spike cleanup.

## Effort and reference class

1.0 day (service + caps 0.2 d, seeding + cleanup 0.2 d, build profile + refresh 0.3 d, tunnel/contract-live 0.15 d, acceptance-pi + perf e2e 0.15 d). Reference class: adding a stateful sidecar service to a single-host compose stack.
