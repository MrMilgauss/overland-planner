"""The retrace rule (ADR-017 section 2, ADR-009 Amendment 3): the one place that says what an arc t -> j is.
Pure domain; the tour model, the plan assembler and the invariant guard all read the arc through it.

A road leaves t's exit toward j's entry at any level: the arc is a `road` (identical points are one: 0 m, nothing to
drive). Else, a track whose entry differs from its exit may be driven as stored and retraced back to its entry, and
the road then leaves from there: a `retrace`, if entry(t) -> entry(j) is connected. Everything else is `forbidden`. A
POI is never retraced, and a loop track has no other end to retrace to.
"""

from __future__ import annotations

from typing import Literal

from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.project_snapshot import left_at, reached_at
from overland_planner.domain.routing.road_leg import LegTable, RoadPair

ArcKind = Literal["road", "retrace", "forbidden"]


def second_pass_pair(previous: CatalogItem, successor: CatalogItem, legs: LegTable) -> RoadPair | None:
    """The pair entry(t) -> entry(j) to ask next: only for a retraceable track with no road from its exit."""
    if not isinstance(previous, TrackItem) or previous.entry == previous.exit:
        return None
    if legs.connected(left_at(previous), reached_at(successor)):
        return None
    return previous.entry, reached_at(successor)


def arc_kind(previous: CatalogItem, successor: CatalogItem, legs: LegTable) -> ArcKind:
    """The arc from `previous` to `successor`; `legs` holds the first pass, and the second pass where one was asked."""
    if legs.connected(left_at(previous), reached_at(successor)):
        return "road"
    retrace = second_pass_pair(previous, successor, legs)
    return "retrace" if retrace is not None and legs.connected(*retrace) else "forbidden"
