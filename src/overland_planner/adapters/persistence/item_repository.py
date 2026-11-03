"""`ItemRepository` on SQLAlchemy Core: catalog items (`items`) with their track details (`tracks`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, func, select

from overland_planner.adapters.persistence.tables import items, tracks
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.catalog.item import TrackItem


class SqlAlchemyItemRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, item: TrackItem) -> None:
        last = self._connection.execute(
            select(func.max(items.c.position)).where(items.c.project_id == item.project_id)
        ).scalar_one()
        self._connection.execute(
            items.insert().values(
                id=item.id,
                project_id=item.project_id,
                type=item.type,
                name=item.name,
                included=item.included,
                position=(last or 0) + 1,
            )
        )
        self._connection.execute(
            tracks.insert().values(
                item_id=item.id,
                description=item.description,
                original_sha256=item.original_sha256,
                direction_version=item.direction_version,
                canonical_sha256=item.canonical_sha256,
                point_count=item.point_count,
                entry_lat=item.entry.latitude,
                entry_lon=item.entry.longitude,
                exit_lat=item.exit.latitude,
                exit_lon=item.exit.longitude,
                length_m=item.length_m,
            )
        )

    def list(self, project_id: str) -> list[TrackItem]:
        query = (
            select(items, tracks)
            .join(tracks, tracks.c.item_id == items.c.id)
            .where(items.c.project_id == project_id)
            .order_by(items.c.position)
        )
        return [_track(row) for row in self._connection.execute(query).mappings()]


def _track(row: Any) -> TrackItem:
    return TrackItem(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        description=row["description"],
        original_sha256=row["original_sha256"],
        canonical_sha256=row["canonical_sha256"],
        direction_version=row["direction_version"],
        point_count=row["point_count"],
        entry=Coordinate(row["entry_lat"], row["entry_lon"]),
        exit=Coordinate(row["exit_lat"], row["exit_lon"]),
        length_m=row["length_m"],
        included=row["included"],
    )
