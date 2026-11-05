"""In-memory doubles of the catalog's driven ports for unit tests (they honour the production Protocols).

`InMemoryCatalog` stands for the database: units of work stage their changes and only `commit()` publishes them, like
the SQLite adapter. `InMemoryFileStore` stands for `DATA_DIR/files`, keyed by the relative path the layout gives
each file (brief §9); `failing=True` makes every write raise `OSError` like a full disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from overland_planner.application.ports.file_store import CanonicalPointsMissing
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.domain.catalog.item import CatalogItem
from overland_planner.domain.catalog.project import Project


@dataclass
class InMemoryCatalog:
    projects: dict[str, Project] = field(default_factory=dict)
    items: list[CatalogItem] = field(default_factory=list)
    commits: int = 0

    def unit_of_work(self) -> InMemoryCatalogUnitOfWork:
        return InMemoryCatalogUnitOfWork(self)


class _Projects:
    def __init__(self, rows: dict[str, Project]) -> None:
        self._rows = rows

    def add(self, project: Project) -> None:
        self._rows[project.id] = project

    def get(self, project_id: str) -> Project | None:
        return self._rows.get(project_id)

    def list(self) -> list[Project]:
        return list(self._rows.values())

    def update(self, project: Project) -> None:
        self._rows[project.id] = project


class _Items:
    def __init__(self, rows: list[CatalogItem]) -> None:
        self._rows = rows

    def add(self, item: CatalogItem) -> None:
        self._rows.append(item)

    def get(self, item_id: str) -> CatalogItem | None:
        return next((item for item in self._rows if item.id == item_id), None)

    def list(self, project_id: str) -> list[CatalogItem]:
        return [item for item in self._rows if item.project_id == project_id]


class InMemoryCatalogUnitOfWork:
    def __init__(self, catalog: InMemoryCatalog) -> None:
        self._catalog = catalog
        self._projects: dict[str, Project] = {}
        self._items: list[CatalogItem] = []
        self.projects = _Projects(self._projects)
        self.items = _Items(self._items)

    def __enter__(self) -> Self:
        self._projects.update(self._catalog.projects)
        self._items.extend(self._catalog.items)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._projects.clear()
        self._items.clear()

    def commit(self) -> None:
        self._catalog.projects = dict(self._projects)
        self._catalog.items = list(self._items)
        self._catalog.commits += 1


class InMemoryFileStore:
    def __init__(self, *, failing: bool = False) -> None:
        self.files: dict[str, bytes] = {}
        self._failing = failing

    def keep_original(self, sha256: str, content: bytes) -> None:
        self._write(f"originals/{sha256}.gpx", content, keep_existing=True)

    def keep_canonical_points(self, track_id: str, direction_version: int, content: bytes) -> None:
        self._write(self._canonical_path(track_id, direction_version), content, keep_existing=False)

    def read_canonical_points(self, track_id: str, direction_version: int) -> bytes | CanonicalPointsMissing:
        assert track_id, "a track id names the folder of its canonical files"
        assert direction_version >= 1, "direction versions are numbered from 1"
        content = self.files.get(self._canonical_path(track_id, direction_version))
        return CanonicalPointsMissing() if content is None else content

    def lose_canonical_points(self, track_id: str, direction_version: int) -> None:
        """The file vanishes behind the planner's back."""
        del self.files[self._canonical_path(track_id, direction_version)]

    @staticmethod
    def _canonical_path(track_id: str, direction_version: int) -> str:
        return f"tracks/{track_id}/canonical.v{direction_version}.json"

    def _write(self, path: str, content: bytes, *, keep_existing: bool) -> None:
        if self._failing:
            raise OSError("No space left on device")
        if not (keep_existing and path in self.files):
            self.files[path] = content

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


class RecordingEventLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self._levels: list[tuple[str, str]] = []

    def info(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))
        self._levels.append((event, "info"))

    def warning(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))
        self._levels.append((event, "warning"))

    def fields_of(self, event: str) -> list[dict[str, object]]:
        """The fields of every line logged as `event`, in order."""
        return [fields for logged, fields in self.events if logged == event]

    def levels_of(self, event: str) -> list[str]:
        """The level of every line logged as `event`, in order."""
        return [level for logged, level in self._levels if logged == event]

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")
