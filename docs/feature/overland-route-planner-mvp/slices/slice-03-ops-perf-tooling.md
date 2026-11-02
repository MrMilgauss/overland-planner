# Slice 03-ops (enabler): Golden order and Pi performance tooling

Priority: 4a | Type: enabler (no user story; D145, OD-1) | Enables: US-06a S1a, S3 and the `@technical` "The 60-item plan is the same on every machine" | job_id: infrastructure-only | infrastructure_rationale: slice 03's 3-minute claim can only be verified with a reproducible 60-item fixture and a repeatable measurement on the Pi; this tooling is that measurement

## Goal

The 60-item benchmark fixtures exist in the repository with a committed golden order, CI checks that every machine finds the same order, and `make perf-pi` measures the solve stage on Marco's Pi on demand.

## IN

- Pre-requisite (OD-7, SPIKE-1): re-create the seeded instance generator (seed 20261101, 68 Western Alps places, method in `spike/findings.md` Setup) and commit fixtures I1/I2 (60 items + Start + End = 62 stops, D146) with the golden order hash
- CI job `golden-order` (blocking, from this slice on; added to the publish `needs` here)
- `make perf-pi` in mock-matrix mode (solve stage): N=10 gate, slowest of 10 <= 55 s (D159); N=30 for re-calibration; every run counts (D147); the Pi also solves I1/I2 and compares the hash (F-19)

## OUT

- End-to-end mode of `perf-pi` with live Valhalla (slice 06a-ops); the solver features themselves (slice 03)

## Done when

- The golden hash is identical on Mac, amd64 CI and the Pi
- `make perf-pi` prints the slowest-of-10 solve time and the stage timings

## Demo

Shown with slice 03 (Marco watches the 60-item measurement on his Pi).

## Dependencies

Slice 02 (solver model). The user names the start time of any Pi run.

## Effort and reference class

0.9 day (fixture generator + golden 0.3 d, CI job 0.2 d, perf-pi + Pi golden check 0.4 d). Reference class: benchmark harness over an existing API.
