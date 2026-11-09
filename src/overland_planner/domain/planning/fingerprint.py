"""The fingerprint of a plan's solver inputs, the key of the fingerprint memo (ADR-014 section 5, FR-5.6). Pure domain.

SHA-256 over the canonical model as far as it exists today: the node item ids in model order, each node's quantised
location (a POI) or entry and exit with `direction_version` and `canonical_sha256` (a track), every arc cost, the
objective, the road map's `provider_id`, the budget and the solver identity the solver adapter publishes. The weighting
mode, the phase limits and the retrace penalties (D124) do not exist yet: the scheme version leads both the hashed text
and the value, so a later scheme that adds inputs misses instead of hitting an old memo. The off-road speed, the names
and the Excluded items are not inputs: they change the totals or nothing, never the order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import CatalogItem, TrackItem
from overland_planner.domain.planning.project_snapshot import ProjectSnapshot
from overland_planner.domain.planning.solver_model_builder import TourModel

FINGERPRINT_SCHEME = "fp1"
_COORDINATE_DECIMALS = 6  # about 0.1 m


@dataclass(frozen=True)
class SolveSettings:
    """What the solve depends on besides the model."""

    objective: str
    provider_id: str
    budget: int
    solver_identity: str


@dataclass(frozen=True)
class Fingerprint:
    value: str

    @classmethod
    def of(cls, snapshot: ProjectSnapshot, model: TourModel, settings: SolveSettings) -> Fingerprint:
        canonical = {
            "scheme": FINGERPRINT_SCHEME,
            "nodes": [_node(snapshot.item(item_id)) for item_id in model.node_item_ids],
            "start_node": model.start_node,
            "end_node": model.end_node,
            "arc_m": model.arc_m,
            "objective": settings.objective,
            "provider_id": settings.provider_id,
            "budget": settings.budget,
            "solver": settings.solver_identity,
        }
        text = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return cls(f"{FINGERPRINT_SCHEME}:{hashlib.sha256(text.encode()).hexdigest()}")


def _node(item: CatalogItem) -> list[object]:
    if isinstance(item, TrackItem):
        return [
            "track",
            item.id,
            _quantised(item.entry),
            _quantised(item.exit),
            item.direction_version,
            item.canonical_sha256,
        ]
    return ["poi", item.id, _quantised(item.location)]


def _quantised(point: Coordinate) -> list[float]:
    return [round(point.latitude, _COORDINATE_DECIMALS), round(point.longitude, _COORDINATE_DECIMALS)]
