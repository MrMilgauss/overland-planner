"""Step 08-05: `make tiles-refresh` runs scripts/tiles-refresh.sh on the Pi (D83, D92, D166, D237, D239, D240).

The real script runs under /bin/bash with the docker, curl, df and flock shims of tests/deploy/shims; `pi.volume` stands
in for the volume overland_valhalla-data (the shim emulates what valhalla-fetch and valhalla-build leave in `build/`).
Assertions are on observable effects: the volume content, routing.env and its .prev, tiles.log, the exit code and the
order of the docker calls. The real refresh (about 40 minutes) is never run offline (D237).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

import pytest

from tests.deploy.conftest import REFRESH_DATE, TILES_FILES, FakePi

SERVED, KEPT, OLDER = "20261101", "20260901", "20260801"
SERVED_ROUTING = f"VALHALLA_TILESET={SERVED}\n"
KEPT_ROUTING = f"VALHALLA_TILESET={KEPT}\n"
STATUS_MODIFIED = "1793560782"  # what the docker shim's valhalla /status answers on the new tileset
OLD_MODIFIED = "1790000000"  # what it answers while the served tileset is the old one
BUILT = {name: f"built {name}\n" for name in TILES_FILES} | {"default_speeds.json": "downloaded default_speeds.json\n"}
SPEEDS_URL = "https://raw.githubusercontent.com/OpenStreetMapSpeeds/schema/master/default_speeds.json"
MUTATING_VERBS = {"up", "stop", "down", "restart", "rm", "kill", "pull", "create", "run"}
LOW_DISK = (
    "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/nvme0n1p2 245000000 225000000 20000000 92% /\n"
)


@pytest.fixture
def serving(pi: FakePi) -> FakePi:
    """valhalla serves tileset 20261101, 20260901 is the rollback tileset, 20260801 an older one."""
    (pi.dir / "routing.env").write_text(SERVED_ROUTING)
    (pi.dir / "routing.env.prev").write_text(KEPT_ROUTING)
    for name in (SERVED, KEPT, OLDER):
        (pi.volume / "tilesets" / name).mkdir(parents=True)
        (pi.volume / "tilesets" / name / "valhalla_tiles.tar").write_text(f"tiles {name}\n")
    (pi.shim_home / "status_by_tileset.json").write_text(json.dumps({SERVED: OLD_MODIFIED}))
    return pi


def tilesets(pi: FakePi) -> list[str]:
    return sorted(p.name for p in (pi.volume / "tilesets").iterdir())


def volume_tree(pi: FakePi) -> dict[str, str]:
    return {str(p.relative_to(pi.volume)): p.read_text() for p in sorted(pi.volume.rglob("*")) if p.is_file()}


def pointers(pi: FakePi) -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(pi.dir.glob("routing.env*"))}


def timeline(pi: FakePi) -> list[str]:
    """One label per docker call, in order: helper runs by their LABEL, compose calls by what they do."""
    labels = []
    for call in pi.calls("docker"):
        argv, joined = call["argv"], " ".join(call["argv"])
        if argv[:1] == ["run"]:
            labels.append(argv[argv.index("-c") + 2])
        elif "run" in argv:
            service = "valhalla-fetch" if "valhalla-fetch" in argv else "valhalla-build"
            step = "overrides" if "--entrypoint" in argv else ("merge" if "osmium merge" in joined else "")
            labels.append(f"run {service}{' ' + step if step else ''}".strip())
        elif "exec" in argv:
            labels.append("status")
        else:
            labels.append(f"{'up' if 'up' in argv else 'stop'} {argv[-1]}")
    return labels


def mutating(pi: FakePi) -> list[str]:
    """What changed or could have changed anything: every call but the read-only tileset-exists probe."""
    return [label for label in timeline(pi) if label != "tileset-exists"]


def last_log(pi: FakePi) -> dict[str, str]:
    return pi.tiles_log()[-1]


def test_refresh_builds_while_serving_stops_for_the_build_switches_and_prunes_only_at_the_end(serving: FakePi) -> None:
    result = serving.tiles_refresh()

    assert result.returncode == 0, result.stderr
    assert timeline(serving) == [
        "tileset-exists",
        "status",  # the old tileset_last_modified, read before the engine is stopped
        "prepare-build",
        "run valhalla-fetch",  # download, valhalla still serving
        "run valhalla-fetch merge",
        "drop-src",
        "stop valhalla",
        "run valhalla-build",
        "run valhalla-build overrides",
        "promote",
        "up valhalla",
        "status",
        "prune-tilesets",
    ]
    new = serving.volume / "tilesets" / REFRESH_DATE
    assert {f.name: f.read_text() for f in new.iterdir() if f.name != "SHA256SUMS"} == {
        name: BUILT[name] for name in TILES_FILES
    }
    sums = "\n".join(f"{hashlib.sha256(BUILT[n].encode()).hexdigest()}  {n}" for n in TILES_FILES) + "\n"
    assert (new / "SHA256SUMS").read_text() == sums
    assert not (serving.volume / "build").exists()
    assert tilesets(serving) == [SERVED, REFRESH_DATE]  # the new and the previous one stay, the older one goes
    assert pointers(serving) == {
        "routing.env": f"VALHALLA_TILESET={REFRESH_DATE}\n",
        "routing.env.prev": SERVED_ROUTING,
    }
    (line,) = serving.tiles_log()
    assert {k: line[k] for k in ("action", "tileset", "tileset_last_modified", "result", "reason")} == {
        "action": "refresh",
        "tileset": REFRESH_DATE,
        "tileset_last_modified": STATUS_MODIFIED,
        "result": "ok",
        "reason": "",
    }
    assert "make contract-live" in result.stderr and "make acceptance-pi" in result.stderr


def test_the_services_run_with_the_overrides_mounted_and_the_extracts_of_the_five_regions(serving: FakePi) -> None:
    serving.tiles_refresh()

    runs = [c["argv"] for c in serving.calls("docker") if "run" in c["argv"] and c["argv"][:1] == ["compose"]]
    assert all(argv[:3] == ["compose", "-p", "overland"] and "--profile" in argv and "--rm" in argv for argv in runs)
    download = " ".join(runs[0])
    for region in ("italy", "switzerland", "austria", "france/rhone-alpes", "france/provence-alpes-cote-d-azur"):
        assert f"https://download.geofabrik.de/europe/{region}-latest.osm.pbf" in download
    overrides = " ".join(runs[-1])
    assert SPEEDS_URL in download and "/work/default_speeds.json" in download
    assert "--entrypoint sh valhalla-build" in overrides and "jq -s" in overrides
    assert "valhalla/valhalla.overrides.json:/overrides.json:ro" in overrides
    assert not list((serving.volume / "tilesets").glob(".*partial"))


def test_the_planner_is_asked_for_its_diagnostics_and_the_user_is_told_a_running_plan_ends(serving: FakePi) -> None:
    result = serving.tiles_refresh()

    (diagnostics,) = [c for c in serving.calls("curl") if c["argv"][-1].endswith("/api/diagnostics")]
    assert diagnostics["argv"][-1] == "http://192.168.1.10:8080/api/diagnostics" and "-K" in diagnostics["argv"]
    assert "stopping the routing engine; a plan being calculated now ends with" in result.stderr
    assert "Routing engine unreachable - nothing was changed" in result.stderr
    assert not any("compose" in c["argv"] and "planner" in c["argv"][-1:] for c in serving.calls("docker"))


def test_a_planner_that_does_not_answer_is_a_note_not_a_refusal(serving: FakePi) -> None:
    serving.rule("curl", "diagnostics", exit=22)

    result = serving.tiles_refresh()

    assert result.returncode == 0, result.stderr
    assert "/api/diagnostics did not answer" in result.stderr
    assert last_log(serving)["result"] == "ok"


def refusal_cases() -> list[Any]:
    def existing_dir(pi: FakePi) -> None:
        (pi.volume / "tilesets" / REFRESH_DATE).mkdir()

    def is_served(pi: FakePi) -> None:
        (pi.dir / "routing.env").write_text(f"VALHALLA_TILESET={REFRESH_DATE}\n")

    def is_rollback(pi: FakePi) -> None:
        (pi.dir / "routing.env.prev").write_text(f"VALHALLA_TILESET={REFRESH_DATE}\n")

    def no_routing(pi: FakePi) -> None:
        (pi.dir / "routing.env").unlink()

    def low_disk(pi: FakePi) -> None:
        pi.rule("df", stdout=LOW_DISK)

    def bigger_cap(pi: FakePi) -> None:
        (pi.dir / ".env").write_text((pi.dir / ".env").read_text() + "VALHALLA_BUILD_MEM=12g\n")

    return [
        pytest.param(existing_dir, {}, 12, "already exists", id="existing_target"),
        pytest.param(is_served, {}, 12, "not overwritten", id="target_is_served"),
        pytest.param(is_rollback, {}, 12, "not overwritten", id="target_is_rollback"),
        pytest.param(no_routing, {}, 12, "make tiles-seed", id="no_routing_env"),
        pytest.param(low_disk, {}, 12, "disk", id="disk"),
        pytest.param(lambda pi: None, {}, 9, "MemAvailable", id="memory_below_cap_plus_1g"),
        pytest.param(bigger_cap, {}, 12, "MemAvailable", id="memory_below_a_bigger_cap_from_dot_env"),
    ]


@pytest.mark.parametrize(("arrange", "env", "gib", "words"), refusal_cases())
def test_every_preflight_refusal_changes_nothing_and_says_why(
    serving: FakePi, arrange: Callable[[FakePi], None], env: dict[str, str], gib: int, words: str
) -> None:
    arrange(serving)
    tree, before = volume_tree(serving), pointers(serving)

    result = serving.tiles_refresh(available_kb=gib * 1024 * 1024, env=env)

    assert result.returncode == 1
    assert words in result.stderr
    assert mutating(serving) == []
    assert (volume_tree(serving), pointers(serving)) == (tree, before)
    assert (last_log(serving)["result"], last_log(serving)["action"]) == ("failed", "refresh")


@pytest.mark.parametrize(
    ("stage", "needle", "stopped"),
    [
        ("download", "curl -fL", False),
        ("download", "default_speeds.json", False),
        ("merge", "osmium merge", False),
        ("build", "-T valhalla-build", True),
        ("overrides", "--entrypoint", True),
    ],
)
def test_a_failure_before_the_promotion_starts_the_old_tileset_again_and_touches_no_pointer(
    serving: FakePi, stage: str, needle: str, stopped: bool
) -> None:
    serving.rule("docker", "run", needle, exit=1)
    before = pointers(serving)

    result = serving.tiles_refresh()

    assert result.returncode == 1
    labels = timeline(serving)
    assert labels[-1] == "up valhalla" and ("stop valhalla" in labels) is stopped
    assert not {"promote", "prune-tilesets"} & set(labels) and labels.count("status") == 1
    assert pointers(serving) == before
    assert tilesets(serving) == [OLDER, KEPT, SERVED]
    assert (last_log(serving)["result"], last_log(serving)["reason"]) == ("failed", f"refresh failed ({stage})")


def test_too_little_memory_just_before_the_merge_stops_the_refresh_while_the_old_tileset_still_serves(
    serving: FakePi,
) -> None:
    (serving.dir / ".env").write_text((serving.dir / ".env").read_text() + "VALHALLA_BUILD_MEM=4g\n")

    result = serving.tiles_refresh(available_kb=6 * 1024 * 1024)  # enough for a 4g build, not for the 7 GiB merge

    assert result.returncode == 1
    assert timeline(serving) == [
        "tileset-exists",
        "status",
        "prepare-build",
        "run valhalla-fetch",
        "up valhalla",
    ]
    assert "7 GB" in result.stderr
    assert last_log(serving)["reason"] == "refresh failed (merge)"


@pytest.mark.parametrize(
    "rule",
    [
        {"args_contain": ["up", "--wait"], "exit": 1},
        {"args_contain": ["exec"], "routing_tileset": REFRESH_DATE, "exit": 1},
        {
            "args_contain": ["exec"],
            "routing_tileset": REFRESH_DATE,
            "stdout": '{"version":"3.8.0","tileset_last_modified":1700000000}',
        },
        {"args_contain": ["exec"], "routing_tileset": REFRESH_DATE, "stdout": '{"version":"3.9.1"}'},
    ],
)
def test_a_failed_switch_restores_the_pointers_serves_the_old_tileset_and_prunes_nothing(
    serving: FakePi, rule: dict[str, Any]
) -> None:
    serving.rule("docker", *rule["args_contain"], **{k: v for k, v in rule.items() if k != "args_contain"})
    before = pointers(serving)

    result = serving.tiles_refresh()

    assert result.returncode == 1
    assert pointers(serving) == before
    labels = timeline(serving)
    assert labels[-1] == "up valhalla" and "prune-tilesets" not in labels
    last_up = [c["argv"] for c in serving.calls("docker") if "up" in c["argv"]][-1]
    assert "--wait" not in last_up
    assert tilesets(serving) == [OLDER, KEPT, SERVED, REFRESH_DATE]  # the new one is kept for inspection
    assert (serving.volume / "tilesets" / REFRESH_DATE / "SHA256SUMS").is_file()
    assert (last_log(serving)["result"], last_log(serving)["reason"]) == ("failed", "refresh failed (switch)")
    assert not [p for p in serving.dir.iterdir() if p.name.endswith(".orig") or ".tmp." in p.name]


@pytest.mark.parametrize("modified", [OLD_MODIFIED, ""])
def test_a_switch_whose_engine_still_serves_the_old_map_data_is_undone(serving: FakePi, modified: str) -> None:
    body = f'{{"version":"3.9.1","tileset_last_modified":{modified}}}' if modified else '{"version":"3.9.1"}'
    serving.rule("docker", "exec", routing_tileset=REFRESH_DATE, stdout=body)
    before = pointers(serving)

    result = serving.tiles_refresh()

    assert result.returncode == 1
    assert ("still serves the old map data" in result.stderr) is bool(modified)
    assert pointers(serving) == before and timeline(serving)[-1] == "up valhalla"
    assert (last_log(serving)["result"], last_log(serving)["reason"]) == ("failed", "refresh failed (switch)")


def test_a_dropped_session_during_the_build_starts_the_old_tileset_and_leaves_the_pointers(serving: FakePi) -> None:
    serving.rule("docker", "-T valhalla-build", kill_parent="TERM")
    before = pointers(serving)

    result = serving.tiles_refresh()

    assert result.returncode == 143
    last_compose = [c["argv"] for c in serving.calls("docker") if c["argv"][:1] == ["compose"]][-1]
    assert last_compose[-3:] == ["up", "-d", "valhalla"]
    assert pointers(serving) == before
    assert [(line["result"], line["reason"]) for line in serving.tiles_log()] == [
        ("failed", "refresh failed (interrupted)")
    ]


def test_an_interruption_after_the_pointers_changed_puts_them_back(serving: FakePi) -> None:
    serving.rule("docker", "up", "--wait", kill_parent="HUP")
    before = pointers(serving)

    result = serving.tiles_refresh()

    assert result.returncode == 129
    assert pointers(serving) == before and timeline(serving)[-1] == "up valhalla"
    assert [line["reason"] for line in serving.tiles_log()] == ["refresh failed (interrupted)"]
    assert not [p for p in serving.dir.iterdir() if p.name.endswith(".orig") or ".tmp." in p.name]


def test_a_probe_that_cannot_inspect_the_volume_is_a_refusal_not_an_absent_tileset(serving: FakePi) -> None:
    serving.rule("docker", "tileset-exists", exit=125)
    tree, before = volume_tree(serving), pointers(serving)

    result = serving.tiles_refresh()

    assert result.returncode == 1 and "cannot inspect the volume" in result.stderr
    assert mutating(serving) == [] and (volume_tree(serving), pointers(serving)) == (tree, before)
    assert last_log(serving)["result"] == "failed"


def test_a_destination_that_appears_before_the_promotion_is_never_written_into(serving: FakePi) -> None:
    serving.rule("docker", "promote", mkdir=f"tilesets/{REFRESH_DATE}", passthrough=True)
    before = pointers(serving)

    result = serving.tiles_refresh()

    assert result.returncode == 1
    assert list((serving.volume / "tilesets" / REFRESH_DATE).iterdir()) == []
    assert pointers(serving) == before and timeline(serving)[-1] == "up valhalla"
    assert last_log(serving)["reason"] == "refresh failed (promote)"


def test_a_routing_env_that_cannot_be_backed_up_changes_no_pointer(serving: FakePi) -> None:
    before = pointers(serving)

    with serving.read_only_install():
        result = serving.tiles_refresh()
        assert pointers(serving) == before

    assert result.returncode == 1 and "cannot back up routing.env" in result.stderr
    assert timeline(serving)[-1] == "up valhalla"
    assert last_log(serving)["result"] == "failed"


def test_every_call_stays_in_project_overland_and_nothing_is_pruned_or_taken_down(serving: FakePi) -> None:
    serving.tiles_refresh()

    for argv in (c["argv"] for c in serving.calls("docker")):
        assert argv[:1] in (["compose"], ["run"]), argv
        assert argv[:1] == ["run"] or argv[:3] == ["compose", "-p", "overland"], argv
        assert "down" not in argv and "prune" not in argv
    helpers = [c["argv"] for c in serving.calls("docker") if c["argv"][:1] == ["run"]]
    assert all("--network" in a and a[a.index("--network") + 1] == "none" for a in helpers)
