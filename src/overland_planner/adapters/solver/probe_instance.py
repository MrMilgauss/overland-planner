"""The solver probe's fixed instance and verdict (ADR-011 Amendment 1, brief §6 and §7). No OR-Tools import here.

A 6-node asymmetric tour from the depot (node 0) back to it, visiting every other node once:
- node 3 is a track: it is entered at one end and left from the other, so every departure from it also pays the
  track's own length (`TRACK_LENGTH`);
- the arc 2 -> 4 is forbidden (a one-way rule). Without that rule the cheapest tour would use it (135 via
  1, 2, 4, 3, 5), so a solver that ignores the rule gives a wrong order.
The unique optimum is 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 0 at cost 152 (checked by enumeration in the integration test).

The probe is ok only when the child exited cleanly and both solves returned that order at that cost; anything else
(crash, hang, wrong or unstable answer) makes the planner degraded-unhealthy with reason `optimizer_unavailable`.
"""

from __future__ import annotations

from dataclasses import dataclass

from overland_planner.application.ports.probe import ProbeResult

NODE_COUNT = 6
DEPOT = 0
TRACK_NODE = 3
TRACK_LENGTH = 60
FORBIDDEN_ARC = (2, 4)
_DISTANCES = (
    (0, 12, 31, 44, 29, 18),
    (21, 0, 9, 27, 38, 33),
    (36, 14, 0, 40, 7, 41),
    (47, 30, 22, 0, 13, 26),
    (25, 40, 19, 11, 0, 8),
    (10, 35, 45, 24, 17, 0),
)
KNOWN_OPTIMAL_ORDER = (1, 2, 3, 4, 5)
KNOWN_OPTIMUM = 152

Solve = tuple[tuple[int, ...], int]  # (visiting order without the depot, objective)

_HEALTHY_SOLVES: tuple[Solve, ...] = ((KNOWN_OPTIMAL_ORDER, KNOWN_OPTIMUM),) * 2
OK = ProbeResult(outcome="ok")
OPTIMIZER_UNAVAILABLE = ProbeResult(outcome="degraded-unhealthy", reason="optimizer_unavailable")


@dataclass(frozen=True)
class ProbeObservation:
    """What the parent saw of the probe child: its exit code (None = still running when killed) and its solves."""

    exit_code: int | None
    solves: tuple[Solve, ...]


def arc_cost(origin: int, destination: int) -> int:
    track = TRACK_LENGTH if origin == TRACK_NODE else 0
    return _DISTANCES[origin][destination] + track


def probe_verdict(observation: ProbeObservation) -> ProbeResult:
    if observation.exit_code == 0 and observation.solves == _HEALTHY_SOLVES:
        return OK
    return OPTIMIZER_UNAVAILABLE
