# Slice 03: A full-size trip planned within budget on the Pi, with Stop

Priority: 4 | Stories: US-06a (J-01), US-06b (J-01) | FR-5.5 (revised), FR-5.6 | Revision 6 (U4-U12)

## Goal

Marco plans a realistic 60-item trip on his Raspberry Pi 5. With the road connections already known, the solve stage finishes on its deterministic search budget within 55 s (p95). He sees how long planning took. He can always press "Stop and use best so far". The optimisation limit returns a labelled best-so-far plan, and the feasibility limit fails the run with a clear message.

## IN

- Deterministic search budget; safety limits: feasibility 10 min, optimisation 30 min counted from pressing Optimize/Recalculate (configurable); labels "not fully optimised (time limit / stopped)" (D15 amended; DESIGN D41, D42, D58)
- "Stop and use best so far" during a run (DESIGN D43, ADR-015); Stop during leg fetching creates no run
- Run time shown ("Planned 60 items in ...")
- No-change Recalculate reuses the identical stored plan ("Reused the identical plan of run #N"), including a "not fully optimised" one; "Re-optimise (ignore previous result)" starts a fresh search (D73, U45)
- Benchmark fixture: 60 items = 60 nodes = 40 tracks + 20 POIs, of which 2 POIs are the anchors (Start "Casa Marco, Torino", End "Briancon"). The road matrix is precomputed in memory and plan reuse is disabled for measurement, so there is no dependency on slice 05 (B7, U10).

## OUT

- End-to-end 180 s with cold legs on Valhalla: US-06a S1b, delivered in slice 06a
- Multi-day splitting (Phase 2)

## Learning hypothesis

Disproves "the optimizer is viable on a Raspberry Pi 5 for 60 items" if no search budget gives solve-stage p95 <= 55 s with road km within 10% of a 30-minute PC search.

## Acceptance criteria (each traces to a scenario)

- [ ] US-06a: "The solve stage for 60 items fits the budget on the Pi" (p95 <= 55 s); "The best plan found is returned when the optimisation limit is reached" (20 s limit -> plan within 25 s, labelled "not fully optimised (time limit)"); "A plan found on the Pi is nearly as good as a long search" (within 10% of a 30-min PC reference); "Marco sees how long planning took"
- [ ] US-06b: "Marco stops a long optimisation and keeps the best route so far"; "Stopping before any valid route fails the run with a reason"; "Stopping while roads are still being looked up changes nothing"; "No valid route within the feasibility limit"; "A later no-change Recalculate returns the same plan as a stopped run" (same "not fully optimised" plan at once, "Re-optimise (ignore previous result)" offered); "Re-optimise starts a fresh search" (D73, U45)
- HC properties at 60 items are covered by the US-03/US-04 property scenarios (range 2-60). The idle RAM guardrail is DoD item 5.

## Production-like data

The 60-item fixture is built from real Western Alps trail entry/exit coordinates (Piedmont, Aosta, Hautes-Alpes), plus a sparse variant with missing pairs for the feasibility checks.

## Dogfood moment

Marco runs his "everything I ever wanted to drive" collection (40 trails) on the Pi and presses Stop once to try it.

## Dependencies

Slice 02 only. OD#5 resolved: Raspberry Pi 5 16 GB, `pi.example` (DESIGN D38) (U14).

## Effort and reference class

1 day after SPIKE-1R (US-06a 0.4 d, US-06b 0.6 d), at risk. Reference class: solver tuning plus a background job with stop (DESIGN ADR-015 already defines the job API).

## Pre-slice SPIKE-1R - MANDATORY GATE (D14 amended, U12)

`/nw-spike` on Marco's Pi 5 with the slice-02 model, a synthetic 60-node asymmetric matrix and a sparse instance.
Kill criterion: no search budget gives solve-stage p95 <= 55 s **and** road km within 10% of a 30-minute PC reference, OR no valid route within 10 min on the sparse instance. Either -> switch to the pre-named fallback `HeuristicTourSolver` (DESIGN D41, D42) or escalate to the user.
