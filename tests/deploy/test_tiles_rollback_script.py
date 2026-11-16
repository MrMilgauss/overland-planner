"""Step 08-04: `make tiles-rollback` runs scripts/tiles-rollback.sh on the Pi (D239; ADR-013 Amendment 3).

The real script runs under /bin/bash with the docker, flock and df shims of tests/deploy/shims; `pi.volume` stands in
for the volume overland_valhalla-data. Assertions are on observable effects: routing.env and its .prev, tiles.log, the
exit code and the compose calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.deploy.conftest import FakePi

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


@pytest.mark.parametrize(
    "rule",
    [
        {"args_contain": ["exec"], "exit": 1},
        {"args_contain": ["exec"], "stdout": '{"version":"3.8.0","tileset_last_modified":1700000000}'},
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


def test_docker_calls_stay_in_project_overland_on_valhalla_only(pi: FakePi) -> None:
    two_tilesets(pi)
    pi.rule("docker", "exec", exit=1)

    pi.tiles_rollback()

    for argv in mutating_compose(pi):
        assert argv[:3] == ["compose", "-p", "overland"] and argv[-1] == "valhalla" and "down" not in argv
    for argv in (c["argv"] for c in pi.calls("docker")):
        assert argv[:1] in (["compose"], ["run"], ["ps"]), argv
