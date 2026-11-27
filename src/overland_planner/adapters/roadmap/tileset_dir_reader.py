"""TilesetStore on the road-map volume (D301, D310, D314): the listing of `ROAD_MAP_DIR`, data only, no matching.

Each directory holds `valhalla_tiles.tar` (its mtime is the map date), `road-map.json` (schema 1, strict, written
only by the refresh) and `outlines/<file>.poly`, read only when the record names the file. A missing volume, a missing,
truncated or unknown-schema record, or a record naming a missing outline is a directory without a record (unknown map,
not an error); an outline that exists and is not a border marks the directory `damaged`, which the probe reports as
`road_map_unreadable`. A missing mount is not degraded. Records are read again only when a file's mtime or size changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from overland_planner.adapters.roadmap.poly_parser import PolyParseError, parse_poly
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.tileset_store import ServedRegion, TilesetListing
from overland_planner.domain.roadmap.outline import Outline
from overland_planner.domain.roadmap.served_map import TilesetEntry

RECORD = "road-map.json"
TAR = "valhalla_tiles.tar"
OUTLINES = "outlines"
_OUTLINE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.poly")
_SERVING = re.compile(r"serving=([0-9A-Za-z][0-9A-Za-z._-]*)")
_MAX_BYTES = 8_000_000  # a record or an outline beyond this is not one of ours


class _Region(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: StrictStr
    name: StrictStr
    parent_name: StrictStr | None
    pbf_url: StrictStr
    outline: StrictStr
    bytes: StrictInt = Field(ge=0)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: StrictInt = Field(alias="schema")
    regions: list[_Region]

    @classmethod
    def read(cls, text: str) -> _Record:
        record = cls.model_validate_json(text)
        if record.schema_version != 1 or not record.regions:
            raise ValueError("not a schema 1 record with regions")
        return record


@dataclass(frozen=True)
class _Read:
    entry: TilesetEntry
    regions: tuple[ServedRegion, ...] | None
    built_at: int
    damaged: bool


class TilesetDirReader:
    def __init__(self, directory: Path | None, progress_file: Path | None = None) -> None:
        self._directory = directory
        self._progress_file = progress_file
        self._kept: dict[str, tuple[tuple[int, ...], _Read]] = {}

    def listing(self) -> TilesetListing:
        reads = [self._read(folder) for folder in self._folders()]
        return TilesetListing(
            entries=tuple(read.entry for read in reads),
            regions={read.entry.name: read.regions for read in reads if read.regions is not None},
            built_at={read.entry.name: read.built_at for read in reads},
            damaged=tuple(read.entry.name for read in reads if read.damaged),
        )

    def serving_hint(self) -> str | None:
        if self._progress_file is None:
            return None
        try:
            text = self._progress_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        for line in text.splitlines():
            found = _SERVING.fullmatch(line.strip())
            if found is not None and found.group(1) not in {".", ".."}:
                return found.group(1)
        return None

    def probe(self) -> ProbeResult:
        damaged = self.listing().damaged
        if damaged:
            return ProbeResult(outcome="degraded-healthy", reason="road_map_unreadable")
        return ProbeResult(outcome="ok")

    def _folders(self) -> list[Path]:
        if self._directory is None:
            return []
        try:
            return sorted(path for path in self._directory.iterdir() if path.is_dir() and not path.is_symlink())
        except OSError:
            return []

    def _read(self, folder: Path) -> _Read:
        signature = _signature(folder)
        kept = self._kept.get(folder.name)
        if kept is not None and kept[0] == signature:
            return kept[1]
        read = _read_folder(folder)
        self._kept[folder.name] = (signature, read)
        return read


def _signature(folder: Path) -> tuple[int, ...]:
    stamps: list[int] = []
    for path in (folder / TAR, folder / RECORD, folder / OUTLINES):
        try:
            seen = path.stat()
            stamps.extend((seen.st_mtime_ns, seen.st_size))
        except OSError:
            stamps.extend((-1, -1))
    return tuple(stamps)


def _mtime(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime) if path.is_file() and not path.is_symlink() else None
    except OSError:
        return None


def _read_folder(folder: Path) -> _Read:
    tar_mtime, record_mtime = _mtime(folder / TAR), _mtime(folder / RECORD)
    built_at = tar_mtime if tar_mtime is not None else record_mtime or 0
    try:
        regions = _regions(folder)
    except _Damaged:
        return _Read(TilesetEntry(folder.name, tar_mtime, False), None, built_at, damaged=True)
    except (OSError, UnicodeDecodeError, ValueError, ValidationError):
        return _Read(TilesetEntry(folder.name, tar_mtime, False), None, built_at, damaged=False)
    return _Read(TilesetEntry(folder.name, tar_mtime, True), regions, built_at, damaged=False)


class _Damaged(Exception):
    """An outline exists and is not a border."""


def _regions(folder: Path) -> tuple[ServedRegion, ...]:
    record_file = folder / RECORD
    if _mtime(record_file) is None or record_file.stat().st_size > _MAX_BYTES:
        raise ValueError("no record")
    record = _Record.read(record_file.read_text(encoding="utf-8"))
    outlines = [_outline(folder, region.outline) for region in record.regions]
    return tuple(
        ServedRegion(region.key, region.name, region.parent_name, region.bytes, outline)
        for region, outline in zip(record.regions, outlines, strict=True)
    )


def _outline(folder: Path, file_name: str) -> Outline:
    if _OUTLINE_FILE.fullmatch(file_name) is None:
        raise ValueError("the record names an outline that is not a plain file name")
    path = folder / OUTLINES / file_name
    if _mtime(path) is None or path.stat().st_size > _MAX_BYTES:
        raise ValueError("the record names an outline that is not there")
    try:
        return parse_poly(path.read_text(encoding="utf-8"))
    except (PolyParseError, UnicodeDecodeError) as unreadable:
        raise _Damaged from unreadable
