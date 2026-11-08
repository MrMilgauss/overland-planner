# S4 replacement probe: property-test solve time (2026-11-08)

Slice 02's recommended spike S4 asked whether the solver supports explicit start/end nodes, an asymmetric matrix and a
deterministic budget. All three were already answered: SPIKE-1R (findings.md, 2026-11-01) proved `solution_limit`
deterministic on Pi and Mac with ortools 9.15.6755, and slice 01b ships `RoutingIndexManager(n, 1, [start], [end])`
with directional exit -> entry arcs and removed missing arcs. The user replaced S4 with this 30-minute timing probe.

Question: how long do the slice 02 `@property` scenarios take with the real solver?

Method: Mac M1, `.venv` Python 3.12, `tour_child._solve` called in-process (no child spawn, ~0.2 s each per
SPIKE-1R e) on random asymmetric models in the Alpine box (lat 44.0-46.5, lon 6.5-8.5), 30% POIs / 70% tracks,
haversine x 1.3 metres, alternating round trip / one-way. Script kept outside the repo.

| items | budget 100 | budget 1,000 | budget 10,000 |
|---|---|---|---|
| 2 | 0.003 s | 0.026 s | 0.25 s |
| 10 | 0.007 s | 0.071 s | 0.68 s |
| 15 | | | 1.27 s |
| 20 | | | 1.85 s |
| 30 | 0.033 s | 0.35 s | 3.6 s |
| 60 | 0.14 s | 1.3 s | 13.0 s |

Every point: a second solve of the same model gave the identical order.

Estimates (Mac; a GitHub ubuntu runner is assumed ~1.5x slower):

- HC-1 / HC-5 / A-2 properties, 1,000 cases, 2-60 items: budget 100 ~1 min each; budget 1,000 ~10 min each.
- A-6 property as written (200 projects x 2 solves, 2-30 items, budget 10,000): ~640 s Mac, ~15-20 min CI. Exceeds
  the `test-python` job's < 11 min on its own.

Raw output was printed to the session only; numbers above are p50.
