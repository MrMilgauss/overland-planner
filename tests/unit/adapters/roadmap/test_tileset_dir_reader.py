"""TilesetDirReader against real folders under tmp_path (adapter integration, no mocks): record schema 1 strict,
outlines named in the record, one fault per test row, and the probe's verdict (D301, D310, D314)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from overland_planner.adapters.roadmap.tileset_dir_reader import TilesetDirReader

SQUARE = "square\n1\n 0.0 0.0\n 0.0 1.0\n 1.0 1.0\n 1.0 0.0\nEND\nEND\n"
EPOCH = 1_795_867_200


def region(key: str, outline: str | None = None, **overrides: Any) -> dict[str, Any]:
    return {
        "key": key,
        "name": key.title(),
        "parent_name": None,
        "pbf_url": f"https://example.invalid/{key}.osm.pbf",
        "outline": outline or f"{key}.poly",
        "bytes": 2_000,
        **overrides,
    }


def tileset(base: Path, name: str, record: Any = None, *, tar: bool = True, poly: str | None = SQUARE) -> Path:
    folder = base / name
    (folder / "outlines").mkdir(parents=True, exist_ok=True)
    record = {"schema": 1, "regions": [region("italy"), region("spain")]} if record is None else record
    text = record if isinstance(record, str) else json.dumps(record)
    (folder / "road-map.json").write_text(text, encoding="utf-8")
    if poly is not None:
        for key in ("italy", "spain"):
            (folder / "outlines" / f"{key}.poly").write_text(poly, encoding="utf-8")
    if tar:
        (folder / "valhalla_tiles.tar").write_bytes(b"tiles")
        os.utime(folder / "valhalla_tiles.tar", (EPOCH, EPOCH))
    return folder


def test_a_valid_tileset_lists_its_entry_date_and_regions(tmp_path: Path) -> None:
    tileset(tmp_path, "20261127")
    listing = TilesetDirReader(tmp_path).listing()
    assert [(e.name, e.tar_mtime, e.has_record) for e in listing.entries] == [("20261127", EPOCH, True)]
    assert listing.built_at == {"20261127": EPOCH}
    assert [(r.key, r.name, r.bytes) for r in listing.regions["20261127"]] == [
        ("italy", "Italy", 2000),
        ("spain", "Spain", 2000),
    ]
    assert listing.damaged == ()


def test_a_tileset_without_a_tar_has_the_date_of_its_record(tmp_path: Path) -> None:
    folder = tileset(tmp_path, "20261127", tar=False)
    os.utime(folder / "road-map.json", (EPOCH, EPOCH))
    listing = TilesetDirReader(tmp_path).listing()
    assert [(e.tar_mtime, e.has_record) for e in listing.entries] == [(None, True)]
    assert listing.built_at == {"20261127": EPOCH}


FAULTS: dict[str, dict[str, Any]] = {
    "no record": {"record": "", "drop_record": True},
    "truncated json": {"record": '{"schema": 1, "regions": [{"key": "ita'},
    "unknown schema": {"record": {"schema": 2, "regions": [region("italy")]}},
    "schema as text": {"record": {"schema": "1", "regions": [region("italy")]}},
    "no regions": {"record": {"schema": 1, "regions": []}},
    "region without a name": {"record": {"schema": 1, "regions": [{"key": "italy", "outline": "italy.poly"}]}},
    "bytes as text": {"record": {"schema": 1, "regions": [region("italy", bytes="12")]}},
    "unknown field": {"record": {"schema": 1, "regions": [region("italy")], "date": "x"}},
    "outline path": {"record": {"schema": 1, "regions": [region("italy", "../italy.poly")]}},
    "outline not on disk": {"record": {"schema": 1, "regions": [region("italy", "gone.poly")]}},
}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_record_that_cannot_be_used_gives_an_entry_without_a_record_and_no_alarm(tmp_path: Path, fault: str) -> None:
    spec = FAULTS[fault]
    folder = tileset(tmp_path, "20261127", spec["record"])
    if spec.get("drop_record"):
        (folder / "road-map.json").unlink()
    reader = TilesetDirReader(tmp_path)
    listing = reader.listing()
    assert [(e.name, e.tar_mtime, e.has_record) for e in listing.entries] == [("20261127", EPOCH, False)]
    assert listing.regions == {} and listing.damaged == ()
    assert reader.probe().outcome == "ok"


@pytest.mark.parametrize("where", ["a missing folder", "no folder given", "a file in its place"])
def test_a_missing_mount_is_an_empty_listing_and_not_degraded(tmp_path: Path, where: str) -> None:
    if where == "a file in its place":
        (tmp_path / "tilesets").write_text("not a folder")
    directory = None if where == "no folder given" else tmp_path / "tilesets"
    reader = TilesetDirReader(directory)
    assert reader.listing().entries == ()
    assert reader.probe().outcome == "ok"


@pytest.mark.parametrize("border", ["this is not a polygon\n", "square\n1\n 0 0\n 1 1\nEND\nEND\n", "\xff"])
def test_a_border_that_is_not_a_border_is_damaged_and_degrades_the_probe(tmp_path: Path, border: str) -> None:
    tileset(tmp_path, "20261127")
    (tmp_path / "20261127" / "outlines" / "spain.poly").write_bytes(border.encode("latin-1"))
    reader = TilesetDirReader(tmp_path)
    listing = reader.listing()
    assert [e.has_record for e in listing.entries] == [False]
    assert listing.damaged == ("20261127",)
    probe = reader.probe()
    assert (probe.outcome, probe.reason) == ("degraded-healthy", "road_map_unreadable")


def test_an_outline_the_record_does_not_name_is_never_read(tmp_path: Path) -> None:
    folder = tileset(tmp_path, "20261127")
    (folder / "outlines" / "stray.poly").write_text("garbage")
    (folder / "outlines" / "stray-dir").mkdir()
    reader = TilesetDirReader(tmp_path)
    assert [e.has_record for e in reader.listing().entries] == [True]
    assert reader.probe().outcome == "ok"


def test_every_directory_is_listed_and_a_bad_one_does_not_spoil_the_others(tmp_path: Path) -> None:
    tileset(tmp_path, "20261101", tar=True)
    tileset(tmp_path, "20261127", {"schema": 2})
    (tmp_path / "stray-file").write_text("x")
    listing = TilesetDirReader(tmp_path).listing()
    assert {e.name: e.has_record for e in listing.entries} == {"20261101": True, "20261127": False}


def test_a_changed_record_is_read_again(tmp_path: Path) -> None:
    folder = tileset(tmp_path, "20261127")
    reader = TilesetDirReader(tmp_path)
    assert len(reader.listing().regions["20261127"]) == 2
    (folder / "road-map.json").write_text(json.dumps({"schema": 1, "regions": [region("italy")]}) + " ")
    assert len(reader.listing().regions["20261127"]) == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("step=building\nserving=20261127\nnew=20261129\n", "20261127"),
        ("serving=20261127", "20261127"),
        ("step=building\n", None),
        ("serving=\n", None),
        ("serving=../etc\n", None),
        ("\xff\xfe", None),
    ],
)
def test_the_serving_line_of_the_progress_note_is_the_hint(tmp_path: Path, text: str, expected: str | None) -> None:
    note = tmp_path / "progress.txt"
    note.write_bytes(text.encode("latin-1"))
    assert TilesetDirReader(tmp_path, progress_file=note).serving_hint() == expected


def test_no_progress_note_is_no_hint(tmp_path: Path) -> None:
    assert TilesetDirReader(tmp_path, progress_file=tmp_path / "progress.txt").serving_hint() is None
    assert TilesetDirReader(tmp_path).serving_hint() is None
