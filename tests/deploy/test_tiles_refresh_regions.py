"""Step 13-15: tiles-refresh.sh rebuilds from REGIONS_FILE (D303, D313-D316; ADR-013 Amendment 5).

Same offline setup as test_tiles_refresh_script.py: the real script, the docker/curl/df/flock shims, real files.
"""

from __future__ import annotations

import fcntl
from pathlib import Path

import pytest

from tests.deploy.conftest import FakePi
from tests.deploy.test_tiles_refresh_script import serving  # noqa: F401 - the fixture

GB = 1_000_000_000
HOST = "https://download.example.invalid"


def regions_file(pi: FakePi, rows: list[tuple[str, int]]) -> dict[str, str]:
    lines = [f"{key}\t{key.title()}\t\t{HOST}/{key}-latest.osm.pbf\t{HOST}/{key}.poly\t{size}" for key, size in rows]
    path = pi.root / "regions.tsv"
    path.write_text("\n".join(lines) + "\n")
    return {"REGIONS_FILE": str(path)}


def disk(pi: FakePi, free_gb: int) -> None:
    kb = free_gb * 1024 * 1024
    pi.rule("df", stdout=f"Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 245000000 1 {kb} 92% /\n")


def fetch_argv(pi: FakePi) -> list[str]:
    runs = [c["argv"] for c in pi.calls("docker") if "valhalla-fetch" in c["argv"]]
    assert runs, "nothing was downloaded"
    return runs[0]


def test_each_region_is_downloaded_on_its_own_with_its_border_fetched_first(serving: FakePi) -> None:  # noqa: F811
    env = regions_file(serving, [("italy", GB), ("portugal", GB)])

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 0, result.stderr[-400:]
    argv = fetch_argv(serving)
    sent = argv[argv.index("download") + 1 :]
    assert sent == [
        "/meta/outlines/italy.poly",
        f"{HOST}/italy.poly",
        "/meta/outlines/portugal.poly",
        f"{HOST}/portugal.poly",
        "/work/default_speeds.json",
        "https://raw.githubusercontent.com/OpenStreetMapSpeeds/schema/master/default_speeds.json",
        "/work/src/1.osm.pbf",
        f"{HOST}/italy-latest.osm.pbf",
        "/work/src/2.osm.pbf",
        f"{HOST}/portugal-latest.osm.pbf",
    ]
    assert not any(
        "italy-latest" in " ".join(c["argv"]) and "geofabrik" in " ".join(c["argv"]) for c in serving.calls()
    )


def test_a_missing_border_stops_the_refresh_before_anything_is_stopped_and_names_the_region(
    serving: FakePi,  # noqa: F811
) -> None:
    env = regions_file(serving, [("italy", GB), ("portugal", GB)])
    serving.rule(
        "docker", "valhalla-fetch", exit=22, stderr="tiles-refresh: not fetched: /meta/outlines/portugal.poly\n"
    )
    tilesets = sorted(p.name for p in (serving.volume / "tilesets").iterdir())

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 1 and "portugal" in result.stderr and "border" in result.stderr
    assert not any("stop" in c["argv"] for c in serving.calls("docker") if c["argv"][:1] == ["compose"])
    assert sorted(p.name for p in (serving.volume / "tilesets").iterdir()) == tilesets
    assert serving.tiles_log()[-1]["result"] == "failed"


@pytest.mark.parametrize(
    ("download_gb", "free_gb", "starts", "need_gb"),
    [(6.4, 26, True, 25), (8, 28, False, 31), (8, 32, True, 31), (1, 24, False, 25), (1, 26, True, 25)],
)
def test_the_disk_needed_is_the_larger_of_25_gb_and_3_9_times_the_download(
    serving: FakePi,  # noqa: F811
    download_gb: float,
    free_gb: int,
    starts: bool,
    need_gb: int,
) -> None:
    env = regions_file(serving, [("portugal", int(download_gb * GB))])
    disk(serving, free_gb)

    result = serving.tiles_refresh(env=env)

    if starts:
        assert result.returncode == 0, result.stderr[-400:]
    else:
        assert result.returncode == 1 and f"only {free_gb} GB free (need {need_gb} GB)" in result.stderr
        assert not any(c["argv"][:1] == ["compose"] for c in serving.calls("docker"))


def test_a_held_lock_exits_75_and_writes_no_failed_line(serving: FakePi) -> None:  # noqa: F811
    with (serving.dir / ".deploy.lock").open("w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = serving.tiles_refresh(env=regions_file(serving, [("portugal", GB)]))

    assert result.returncode == 75 and "already running" in result.stderr
    assert serving.tiles_log() == []
    assert not serving.calls("docker")


@pytest.mark.parametrize(
    "row", ["", "x\ty\t\thttps://a/b.osm.pbf\thttps://a/b.poly\tmany", "../x\ty\t\thttps://a/b\thttps://a/c\t1"]
)
def test_a_list_that_cannot_be_read_is_refused_before_anything_runs(serving: FakePi, row: str) -> None:  # noqa: F811
    path: Path = serving.root / "bad.tsv"
    path.write_text(row + "\n")

    result = serving.tiles_refresh(env={"REGIONS_FILE": str(path)})

    assert result.returncode == 1 and not [c for c in serving.calls("docker") if c["argv"][:1] == ["compose"]]
