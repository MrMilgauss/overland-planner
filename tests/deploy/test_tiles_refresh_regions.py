"""Step 13-15: tiles-refresh.sh rebuilds from REGIONS_FILE (D303, D313-D316; ADR-013 Amendment 5).

Same offline setup as test_tiles_refresh_script.py: the real script, the docker/curl/df/flock shims, real files.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path

import pytest

from tests.deploy.conftest import REFRESH_DATE, TILES_FILES, FakePi
from tests.deploy.test_tiles_refresh_script import SERVED, serving  # noqa: F401 - the fixture

GB = 1_000_000_000
HOST = "https://download.example.invalid"


def outline_name(key: str) -> str:
    return key.replace("/", "-") + ".poly"


def regions_file(pi: FakePi, rows: list[tuple[str, int]]) -> dict[str, str]:
    lines = [f"{key}\t{key.title()}\t\t{HOST}/{key}-latest.osm.pbf\t{HOST}/{key}.poly\t{size}" for key, size in rows]
    return regions_lines(pi, lines, [key for key, _ in rows])


def regions_lines(pi: FakePi, lines: list[str], keys: list[str]) -> dict[str, str]:
    path = pi.root / "regions.tsv"
    path.write_text("\n".join(lines) + "\n")
    # valhalla-fetch leaves the borders it downloaded in the meta folder of the volume; the shim stands for it
    borders = {f"road-map-meta/outlines/{outline_name(key)}": f"border of {key}\n" for key in keys}
    pi.rule("docker", "valhalla-fetch", write=borders, passthrough=True, times=1)
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
    serving.rule(
        "docker", "valhalla-fetch", exit=22, stderr="tiles-refresh: not fetched: /meta/outlines/portugal.poly\n"
    )
    env = regions_file(serving, [("italy", GB), ("portugal", GB)])
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


def new_map(pi: FakePi) -> Path:
    return pi.volume / "tilesets" / REFRESH_DATE


def sum_lines(folder: Path) -> dict[str, str]:
    return {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in (folder / "SHA256SUMS").read_text().splitlines()}


def test_the_record_matches_the_list_line_for_line_and_travels_with_its_borders_under_the_integrity_check(
    serving: FakePi,  # noqa: F811
) -> None:
    rows = [
        "italy\tItaly\t\thttps://h.invalid/italy.osm.pbf\thttps://h.invalid/italy.poly\t1500",
        'us/utah\tUtah "Beehive" \\ Zürich\tUnited States\thttps://h.invalid/utah.osm.pbf\thttps://h.invalid/utah.poly\t7',
    ]
    env = regions_lines(serving, rows, ["italy", "us/utah"])

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 0, result.stderr[-400:]
    folder = new_map(serving)
    assert json.loads((folder / "road-map.json").read_text(encoding="utf-8")) == {
        "schema": 1,
        "regions": [
            {
                "key": "italy",
                "name": "Italy",
                "parent_name": None,
                "pbf_url": "https://h.invalid/italy.osm.pbf",
                "outline": "italy.poly",
                "bytes": 1500,
            },
            {
                "key": "us/utah",
                "name": 'Utah "Beehive" \\ Zürich',
                "parent_name": "United States",
                "pbf_url": "https://h.invalid/utah.osm.pbf",
                "outline": "us-utah.poly",
                "bytes": 7,
            },
        ],
    }
    assert sorted(p.name for p in (folder / "outlines").iterdir()) == ["italy.poly", "us-utah.poly"]
    sums = sum_lines(folder)
    assert sorted(sums) == sorted([*TILES_FILES, "road-map.json", "outlines/italy.poly", "outlines/us-utah.poly"])
    assert all(hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest for name, digest in sums.items())
    assert not (serving.volume / "road-map-meta" / "road-map.json").exists()  # it moved, it was not copied


def test_a_run_without_a_list_writes_no_record_and_a_leftover_of_an_earlier_run_never_reaches_one(
    serving: FakePi,  # noqa: F811
) -> None:
    leftover = serving.volume / "road-map-meta"
    (leftover / "outlines").mkdir(parents=True)
    (leftover / "road-map.json").write_text("{}")
    (leftover / "outlines" / "old.poly").write_text("old\n")

    result = serving.tiles_refresh()

    assert result.returncode == 0, result.stderr[-400:]
    assert sorted(p.name for p in new_map(serving).iterdir()) == sorted([*TILES_FILES, "SHA256SUMS"])
    assert sorted(sum_lines(new_map(serving))) == sorted(TILES_FILES)


def test_prepare_build_empties_the_meta_folder_so_a_leftover_never_reaches_the_record(
    serving: FakePi,  # noqa: F811
) -> None:
    leftover = serving.volume / "road-map-meta"
    (leftover / "outlines").mkdir(parents=True)
    (leftover / "outlines" / "old.poly").write_text("old\n")
    (leftover / "road-map.json").write_text("{}")

    result = serving.tiles_refresh(env=regions_file(serving, [("portugal", GB)]))

    assert result.returncode == 0, result.stderr[-400:]
    assert sorted(p.name for p in (new_map(serving) / "outlines").iterdir()) == ["portugal.poly"]
    assert json.loads((new_map(serving) / "road-map.json").read_text())["regions"][0]["key"] == "portugal"


def test_a_failed_run_leaves_no_meta_in_the_new_tileset(serving: FakePi) -> None:  # noqa: F811
    env = regions_file(serving, [("portugal", GB)])
    serving.rule("docker", "valhalla-build", exit=1)

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 1
    assert REFRESH_DATE not in sorted(p.name for p in (serving.volume / "tilesets").iterdir())
    assert not list((serving.volume / "tilesets").glob("*/road-map.json"))


def test_a_border_the_record_names_but_the_download_did_not_leave_fails_before_anything_is_stopped(
    serving: FakePi,  # noqa: F811
) -> None:
    env = regions_file(serving, [("portugal", GB)])
    (serving.shim_home / "rules.json").write_text("[]")  # the shim leaves no border behind

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 1 and "portugal" in result.stderr
    assert not any("stop" in c["argv"] for c in serving.calls("docker") if c["argv"][:1] == ["compose"])
    assert serving.tiles_log()[-1]["result"] == "failed"


# ------------------------------------------------------------------------------ step 13-17: the refresh reports (D303)
def changes_dir(pi: FakePi) -> Path:
    return pi.shim_home / "volumes" / "overland_road-map"


def note(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def progress_calls(pi: FakePi) -> list[list[str]]:
    return [c["argv"] for c in pi.calls("docker") if c["argv"][:1] == ["run"] and "progress" in c["argv"]]


def test_asked_to_report_the_refresh_names_its_steps_in_order_around_the_stop_and_the_promote(
    serving: FakePi,  # noqa: F811
) -> None:
    env = regions_file(serving, [("portugal", GB)]) | {"ROAD_MAP_PROGRESS": "on"}

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 0, result.stderr[-400:]
    calls = serving.calls("docker")
    steps = [(i, c["argv"][c["argv"].index("progress") + 1]) for i, c in enumerate(calls) if "progress" in c["argv"]]
    assert [s for _, s in steps] == ["checking", "downloading", "building", "switching"]
    at = dict((s, i) for i, s in steps)
    stop = next(i for i, c in enumerate(calls) if c["argv"][:1] == ["compose"] and "stop" in c["argv"])
    promote = next(i for i, c in enumerate(calls) if "promote" in c["argv"])
    assert at["building"] < stop and at["switching"] < promote
    written = note(changes_dir(serving) / "progress.txt")
    assert (written["step"], written["serving"], written["new"]) == ("switching", SERVED, REFRESH_DATE)
    assert {"step_at", "build_started_at"} <= written.keys() and int(written["build_started_at"]) <= int(
        written["step_at"]
    )
    assert not (changes_dir(serving) / "failure.txt").exists()


def test_the_hook_runs_in_the_pinned_container_of_the_helper_with_every_limit(serving: FakePi) -> None:  # noqa: F811
    env = regions_file(serving, [("portugal", GB)]) | {"ROAD_MAP_PROGRESS": "on"}

    serving.tiles_refresh(env=env)

    argv = progress_calls(serving)[0]
    assert argv[argv.index("--user") + 1] == "10001:10001" and argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--cap-drop") + 1] == "ALL" and "--read-only" in argv
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    assert "--pids-limit" in argv and "--memory" in argv
    assert [a for a in argv if ":/vol" in a] == ["overland_road-map:/vol"]


def test_not_asked_the_refresh_makes_no_progress_call(serving: FakePi) -> None:  # noqa: F811
    result = serving.tiles_refresh(env=regions_file(serving, [("portugal", GB)]))

    assert result.returncode == 0 and progress_calls(serving) == []
    assert not changes_dir(serving).exists() or not list(changes_dir(serving).iterdir())


def facts_of_failure(pi: FakePi) -> dict[str, str]:
    return note(changes_dir(pi) / "failure.txt")


def test_a_disk_refusal_reports_its_code_with_the_free_and_the_needed_gb(serving: FakePi) -> None:  # noqa: F811
    disk(serving, 12)
    env = regions_file(serving, [("portugal", GB)]) | {"ROAD_MAP_PROGRESS": "on"}

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 1
    assert facts_of_failure(serving) == {"code": "disk", "free_gb": "12", "need_gb": "25"}


def test_a_memory_refusal_reports_its_code_with_the_available_and_the_needed_gb(serving: FakePi) -> None:  # noqa: F811
    env = regions_file(serving, [("portugal", GB)]) | {"ROAD_MAP_PROGRESS": "on"}

    result = serving.tiles_refresh(available_kb=3 * 1024 * 1024, env=env)

    assert result.returncode == 1
    assert facts_of_failure(serving) == {"code": "memory", "have_gb": "3", "need_gb": "10"}


@pytest.mark.parametrize(
    ("rule", "code"),
    [
        ({"args_contain": ["valhalla-fetch", "download"], "exit": 22}, "download"),
        (
            {
                "args_contain": ["valhalla-fetch", "download"],
                "exit": 22,
                "stderr": "tiles-refresh: not fetched: /meta/outlines/portugal.poly\n",
            },
            "region_missing",
        ),
        ({"args_contain": ["valhalla-fetch", "merge"], "exit": 1}, "merge"),
        ({"args_contain": ["-T valhalla-build"], "exit": 137}, "build_oom"),
        ({"args_contain": ["promote"], "exit": 1}, "promote"),
    ],
)
def test_a_failed_stage_reports_its_code(serving: FakePi, rule: dict, code: str) -> None:  # noqa: F811
    serving.rule("docker", *rule["args_contain"], **{k: v for k, v in rule.items() if k != "args_contain"}, times=1)
    env = regions_file(serving, [("portugal", GB)]) | {"ROAD_MAP_PROGRESS": "on"}

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 1, result.stderr[-300:]
    assert facts_of_failure(serving)["code"] == code


def test_a_held_lock_reports_no_failure_and_exits_75(serving: FakePi) -> None:  # noqa: F811
    env = regions_file(serving, [("portugal", GB)]) | {"ROAD_MAP_PROGRESS": "on"}
    with (serving.dir / ".deploy.lock").open("w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = serving.tiles_refresh(env=env)

    assert result.returncode == 75 and progress_calls(serving) == []


def test_a_progress_write_that_fails_is_one_warning_and_the_refresh_still_succeeds(serving: FakePi) -> None:  # noqa: F811
    env = regions_file(serving, [("portugal", GB)]) | {"ROAD_MAP_PROGRESS": "on"}
    serving.rule("docker", "overland_road-map", exit=125)

    result = serving.tiles_refresh(env=env)

    assert result.returncode == 0, result.stderr[-400:]
    assert serving.tiles_log()[-1]["result"] == "ok"
    assert result.stderr.count("progress could not be written") >= 1
