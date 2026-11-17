"""Routing module facade (brief §3, §11 contract 6): the only `application.routing` import other modules may use."""

from overland_planner.application.routing.leg_resolver import LegResolver, LegsFound, RoadMapKey

__all__ = ["LegResolver", "LegsFound", "RoadMapKey"]
