# Slice 00b: The planner on my home Pi, reachable from home only

Priority: 0b | Stories: US-01a (J-06) | NFR-1, 2, 4, 5, 7 | Revision 7 (final gate, D145): US-01a moved here from slice 01a with the compose/deploy work

## Goal

Marco deploys the CI-green image to his Pi with one command. The planner opens at `pi.example:8080` from his desktop and from Giulia's phone, asks for the shared password when basic auth is on, stays on the home network, and leaves room on the Pi. A failed deploy rolls back by itself.

## IN (DEVOPS D81-D83, D89-D91, D99, D101; fixes F-06, F-07, F-17, F-18)

- `deploy/compose.yaml` with `planner` only (`ROUTING_PROVIDER=mock`), caps (`cpus 1`, 1 GB), hardening, `${PLANNER_BIND:?}` fail-closed, `.env.example` default `127.0.0.1`
- `make deploy` (attestation verify, CI-green gate) -> `deploy.sh`: start on 127.0.0.1, smoke, then publish on `PLANNER_BIND`; auto-rollback; `make rollback/status/logs/diag` (diag = `docker stats` only), `uninstall`, `purge`
- App side of US-01a: optional basic auth, one `app.started` line per start (D155), health check
- e2e CI job on the compose stack (mock)

## OUT

- Items and projects (slice 01a); Valhalla (06a-ops)

## Learning hypothesis

Disproves "a single compose stack runs on Marco's ARM64 Pi next to the household services" if the image does not run on the Pi, idle RAM exceeds 300 MB, or the deploy cannot roll back.

## Acceptance criteria (scenarios in `slice-01a-skeleton-items-on-pi.feature`, retagged `@slice-00b`)

- [ ] US-01a: "Marco brings the planner up on his Pi with one command"; "The same setup runs on Marco's PC"; "Household members are asked for the shared password when basic auth is enabled"; "The planner stays on the home network by default"; "Sharing the planner image never shares Marco's secrets"; "The idle planner leaves room on the Pi"
- [ ] Rollback drill: deploy A -> deploy B -> rollback -> A serving

## Production-like data

None needed (empty planner). The no-backup accepted risk (D153, REQUIREMENTS NFR-3) is stated to Marco at the demo.

## Dogfood moment

Marco runs `make deploy`, opens the planner on his desktop, and Giulia opens it from her phone and is asked for the password.

## Dependencies

Slice 00a. OD#5 resolved: Raspberry Pi 5 16 GB, `pi.example` (DESIGN D38). DEVOPS pre-requisite 5 (Pi `.env`).

## Effort and reference class

1.0 day (deploy/rollback scripts and compose 0.6 d, US-01a app side 0.4 d). Reference class: single-host compose deploy with scripted rollback.
