"""Step 08-04: `make tiles-rollback` runs scripts/tiles-rollback.sh on the Pi (D239; ADR-013 Amendment 3).

The real script runs under /bin/bash with the docker, flock and df shims of tests/deploy/shims; `pi.volume` stands in
for the volume overland_valhalla-data. Assertions are on observable effects: routing.env and its .prev, tiles.log, the
exit code and the compose calls.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from tests.deploy.conftest import FakePi, shim_env

CURRENT_SET = "20261101"
PREVIOUS_SET = "20260901"
CURRENT_ROUTING = f"VALHALLA_TILESET={CURRENT_SET}\n"
PREVIOUS_ROUTING = f"VALHALLA_TILESET={PREVIOUS_SET}\n"
MUTATING_VERBS = {"up", "stop", "down", "restart", "rm", "kill", "pull", "create"}


def mutating_compose(pi: FakePi) -> list[list[str]]:
    return [c["argv"] for c in pi.calls("docker") if c["argv"][:1] == ["compose"] and MUTATING_VERBS & set(c["argv"])]


def two_tilesets(pi: FakePi) -> None:
    (pi.dir / "routing.env").write_text(CURRENT_ROUTING)
    (pi.dir / "routing.env.prev").write_text(PREVIOUS_ROUTING)
    for name in (CURRENT_SET, PREVIOUS_SET):
        (pi.volume / "tilesets" / name).mkdir(parents=True)


def test_rollback_swaps_the_pointers_starts_valhalla_checks_status_and_logs_one_line(pi: FakePi) -> None:
    two_tilesets(pi)

    result = pi.tiles_rollback()

    assert result.returncode == 0, result.stderr
    assert (pi.dir / "routing.env").read_text() == PREVIOUS_ROUTING
    assert (pi.dir / "routing.env.prev").read_text() == CURRENT_ROUTING
    (up,) = mutating_compose(pi)
    assert up[-1] == "valhalla" and "up" in up and "--wait" in up and "--profile" in up
    (status,) = [c["argv"] for c in pi.calls("docker") if "exec" in c["argv"]]
    assert status[-1] == "http://127.0.0.1:8002/status"
    (line,) = pi.tiles_log()
    assert (line["action"], line["tileset"], line["result"]) == ("rollback", PREVIOUS_SET, "ok")


@pytest.mark.parametrize("with_record", [False, True])
def test_rollback_works_on_a_directory_with_and_without_a_record_and_changes_no_file(
    pi: FakePi, with_record: bool
) -> None:
    two_tilesets(pi)
    previous = pi.volume / "tilesets" / PREVIOUS_SET
    if with_record:
        (previous / "outlines").mkdir()
        (previous / "road-map.json").write_text('{"schema":1,"regions":[]}')
        (previous / "outlines" / "portugal.poly").write_text("portugal\n")
    before = sorted(str(p.relative_to(pi.volume)) for p in pi.volume.rglob("*"))

    result = pi.tiles_rollback()

    assert result.returncode == 0, result.stderr
    assert (pi.dir / "routing.env").read_text() == PREVIOUS_ROUTING
    assert sorted(str(p.relative_to(pi.volume)) for p in pi.volume.rglob("*")) == before


def test_the_modified_value_of_the_served_tileset_is_read_back_from_the_last_ok_line(pi: FakePi) -> None:
    two_tilesets(pi)
    assert pi.tiles_rollback().returncode == 0
    reader = "cd {dir} && . scripts/lib.sh && logged_modified {name}"

    served, other = (
        subprocess.run(
            ["bash", "-c", reader.format(dir=pi.dir, name=name)], capture_output=True, text=True, check=False
        ).stdout.strip()
        for name in (PREVIOUS_SET, CURRENT_SET)
    )

    assert (served, other) == ("1793560782", "")  # the rollback line counts; a tileset never proven has none


@pytest.mark.parametrize("mode", ["", "RO", "rw ", "ro,rw", "x"])
def test_the_volume_helper_takes_only_ro_or_rw_and_never_falls_back_to_writable(pi: FakePi, mode: str) -> None:
    result = subprocess.run(
        ["bash", "-c", f". {pi.dir}/scripts/lib.sh && volume_sh '{mode}' 'true'"],
        capture_output=True,
        text=True,
        check=False,
        env=shim_env(pi.shim_home, HOME=str(pi.root)),
    )

    assert result.returncode != 0
    assert result.stderr.strip().count("\n") == 0 and "ro" in result.stderr and "rw" in result.stderr
    assert not pi.calls("docker")


@pytest.mark.parametrize(
    "rule",
    [
        {"args_contain": ["exec"], "exit": 1},
        {"args_contain": ["exec"], "stdout": '{"version":"3.8.0","tileset_last_modified":1700000000}'},
        {"args_contain": ["exec"], "stdout": '{"version":"3.9.1"}'},
    ],
)
def test_a_failed_check_swaps_back_starts_the_engine_on_the_tileset_it_came_from_and_fails(
    pi: FakePi, rule: dict[str, Any]
) -> None:
    two_tilesets(pi)
    pi.rule("docker", *rule["args_contain"], **{k: v for k, v in rule.items() if k != "args_contain"})

    result = pi.tiles_rollback()

    assert result.returncode == 1
    assert (pi.dir / "routing.env").read_text() == CURRENT_ROUTING
    assert (pi.dir / "routing.env.prev").read_text() == PREVIOUS_ROUTING
    ups = [argv for argv in mutating_compose(pi) if "up" in argv]
    assert len(ups) == 2 and all(argv[-1] == "valhalla" for argv in ups)  # the attempt, then back on where it came from
    assert pi.tiles_log()[-1]["result"] == "failed"
    assert not [p for p in pi.dir.iterdir() if p.name.endswith(".orig") or ".tmp." in p.name]


@pytest.mark.parametrize("case", ["no_prev_file", "directory_gone", "no_routing_env"])
def test_without_a_usable_previous_tileset_it_refuses_and_changes_nothing(pi: FakePi, case: str) -> None:
    two_tilesets(pi)
    if case == "no_prev_file":
        (pi.dir / "routing.env.prev").unlink()
    elif case == "directory_gone":
        (pi.volume / "tilesets" / PREVIOUS_SET).rmdir()
    else:
        (pi.dir / "routing.env").unlink()
        (pi.dir / "routing.env.prev").unlink()
    before = {p.name: p.read_text() for p in pi.dir.glob("routing.env*")}

    result = pi.tiles_rollback()

    assert result.returncode == 1
    assert "tiles-rollback:" in result.stderr
    assert {p.name: p.read_text() for p in pi.dir.glob("routing.env*")} == before
    assert not mutating_compose(pi)
    assert pi.tiles_log()[-1]["result"] == "failed"


def test_a_probe_that_cannot_inspect_the_volume_is_a_refusal_not_a_missing_tileset(pi: FakePi) -> None:
    two_tilesets(pi)
    pi.rule("docker", "tileset-exists", exit=125)

    result = pi.tiles_rollback()

    assert result.returncode == 1 and "cannot inspect the volume" in result.stderr
    assert "no longer in the volume" not in result.stderr and not mutating_compose(pi)
    assert (pi.dir / "routing.env").read_text() == CURRENT_ROUTING


def test_a_routing_env_that_cannot_be_backed_up_stops_before_any_change(pi: FakePi) -> None:
    two_tilesets(pi)

    with pi.read_only_install():
        result = pi.tiles_rollback()

    assert result.returncode == 1 and "cannot back up routing.env" in result.stderr
    assert (pi.dir / "routing.env").read_text() == CURRENT_ROUTING and not mutating_compose(pi)
    assert pi.tiles_log()[-1]["result"] == "failed"


def test_a_dropped_session_while_valhalla_starts_swaps_the_pointers_back_and_restarts_the_engine(pi: FakePi) -> None:
    two_tilesets(pi)
    pi.rule("docker", "up", "--wait", kill_parent="TERM", times=1)

    result = pi.tiles_rollback()

    assert result.returncode == 143
    assert (pi.dir / "routing.env").read_text() == CURRENT_ROUTING
    assert (pi.dir / "routing.env.prev").read_text() == PREVIOUS_ROUTING
    assert len([argv for argv in mutating_compose(pi) if "up" in argv]) == 2
    assert "interrupted" in pi.tiles_log()[-1]["reason"] and pi.tiles_log()[-1]["result"] == "failed"


def test_docker_calls_stay_in_project_overland_on_valhalla_only(pi: FakePi) -> None:
    two_tilesets(pi)
    pi.rule("docker", "exec", exit=1)

    pi.tiles_rollback()

    for argv in mutating_compose(pi):
        assert argv[:3] == ["compose", "-p", "overland"] and argv[-1] == "valhalla" and "down" not in argv
    for argv in (c["argv"] for c in pi.calls("docker")):
        assert argv[:1] in (["compose"], ["run"], ["ps"]), argv
