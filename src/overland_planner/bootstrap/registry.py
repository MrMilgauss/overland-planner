"""Typed probe registry (ADR-011 Amendment 1): the composition root registers every wired adapter here.

`register` accepts only a `Probeable`, so mypy strict rejects an adapter that cannot prove it works.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from overland_planner.application.ports.probe import Probeable


class ProbeRegistry:
    def __init__(self) -> None:
        self._components: dict[str, Probeable] = {}

    def register(self, name: str, component: Probeable) -> None:
        self._components[name] = component

    def components(self) -> Mapping[str, Probeable]:
        return MappingProxyType(self._components)
