"""Which Included items no order can connect (ADR-016 section 3, FR-8.2): the check before any solve. Pure domain.

An item is reported when it has no arc in, no arc out, no path from the Start or no path to the End, over the arcs of
the tour model (retrace arcs included: a dead-end track whose entry can be reached has an arc out through its retrace).
The Start needs an arc out only and the End an arc in only; a round trip names one place at both ends, so only the
nodes between them are judged. A single missing pair never reports an item while another order connects it (FR-8.2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from overland_planner.domain.planning.solver_model_builder import TourModel


def unreachable_item_ids(model: TourModel) -> tuple[str, ...]:
    """The ids of the items between the Start and the End the model's arcs cut off, in node order."""
    arcs = model.arc_m

    def runs(origin: int, destination: int) -> bool:
        return arcs[origin][destination] is not None

    nodes = range(len(arcs))
    from_start = _closure(model.start_node, lambda node: (to for to in nodes if runs(node, to)))
    to_end = _closure(model.end_node, lambda node: (origin for origin in nodes if runs(origin, node)))
    between = range(model.start_node + 1, model.end_node)
    return tuple(model.node_item_ids[node] for node in between if not (node in from_start and node in to_end))


def _closure(source: int, neighbours: Callable[[int], Iterable[int]]) -> set[int]:
    """The nodes reached from `source` by following `neighbours`, the source included."""
    reached, pending = {source}, [source]
    while pending:
        for node in neighbours(pending.pop()):
            if node not in reached:
                reached.add(node)
                pending.append(node)
    return reached
