"""Step 08-03: `make tiles-seed` runs scripts/tiles-seed.sh on the Pi (D92, D166, D178, D237; ADR-013 Amendment 3).

The real script runs under /bin/bash with docker, df and flock replaced by the shims in tests/deploy/shims: the helper
container's cp / sha256sum / test really act on host directories standing in for the volume overland_valhalla-data
(`pi.volume`). Assertions are on observable effects: the volume content, routing.env and its .prev, tiles.log, the exit
code and the docker calls. The Pi gate (valhalla healthy on tileset 20261101) is the orchestrator's.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from tests.deploy.conftest import SPIKE_MODIFIED, TILES_FILES, TILESET, FakePi

OLD_ROUTING = "VALHALLA_TILESET=20260901\n"
OLDER_ROUTING = "VALHALLA_TILESET=20260801\n"
MUTATING_VERBS = {"up", "stop", "down", "restart", "rm", "kill", "pull", "create", "run"}


def checksums(contents: dict[str, bytes]) -> str:
    return "\n".join(f"{hashlib.sha256(contents[name]).hexdigest()}  {name}" for name in TILES_FILES)


def tileset_dir(pi: FakePi, name: str = TILESET) -> Any:
    return pi.volume / "tilesets" / name


def compose_verbs(pi: FakePi) -> list[list[str]]:
    return [c["argv"] for c in pi.calls("docker") if c["argv"][:1] == ["compose"]]


def mutating_compose(pi: FakePi) -> list[list[str]]:
    return [argv for argv in compose_verbs(pi) if MUTATING_VERBS & set(argv)]


def labels(pi: FakePi) -> list[str]:
    return [argv[argv.index("-c") + 2] for argv in pi.helper_runs()]


@pytest.fixture
def source(pi: FakePi) -> dict[str, bytes]:
    return pi.seed_files()


def test_seed_copies_verifies_points_routing_env_at_the_tileset_and_starts_valhalla(
    pi: FakePi, source: dict[str, bytes]
) -> None:
    result = pi.tiles_seed()

    assert result.returncode == 0, result.stderr
    assert {f.name: f.read_bytes() for f in tileset_dir(pi).iterdir() if f.name != "SHA256SUMS"} == source
    assert (tileset_dir(pi) / "SHA256SUMS").read_text() == checksums(source) + "\n"
    assert not list((pi.volume / "tilesets").glob(".*partial"))
    assert (pi.dir / "routing.env").read_text() == f"VALHALLA_TILESET={TILESET}\n"
    assert not (pi.dir / "routing.env.prev").exists()
    # source sums, tileset check, copy, verify, finalize; then valhalla is started and its /status read
    assert labels(pi) == ["source-sums", "tileset-exists", "copy-tileset", "verify-copy", "finalize-tileset"]
    (up,) = [argv for argv in compose_verbs(pi) if "up" in argv]
    assert up[-1] == "valhalla" and "--wait" in up and "--profile" in up
    (status,) = [argv for argv in compose_verbs(pi) if "exec" in argv]  # inside the compose network, nothing published
    assert "valhalla" in status and status[-1] == "http://127.0.0.1:8002/status"
    assert compose_verbs(pi).index(status) > compose_verbs(pi).index(up)
    (line,) = pi.tiles_log()
    assert {k: line[k] for k in ("action", "tileset", "tileset_last_modified", "result")} == {
        "action": "seed",
        "tileset": TILESET,
        "tileset_last_modified": SPIKE_MODIFIED,
        "result": "ok",
    }
    assert list(line) == ["ts", "action", "tileset", "tileset_last_modified", "result", "reason"]


def test_every_helper_container_has_no_network_the_pinned_image_and_a_read_only_source(
    pi: FakePi, source: dict[str, bytes]
) -> None:
    assert pi.tiles_seed().returncode == 0

    runs = pi.helper_runs()
    assert runs
    for argv in runs:
        assert argv[:4] == ["run", "--rm", "--network", "none"], argv
        assert any(arg.startswith("alpine:3.22@sha256:") for arg in argv)
        assert "sudo" not in argv
        for i, arg in enumerate(argv):
            if arg == "-v" and ":/seed" in argv[i + 1]:
                assert argv[i + 1].endswith(":ro")


def test_the_previous_routing_env_is_kept_as_prev(pi: FakePi, source: dict[str, bytes]) -> None:
    (pi.dir / "routing.env").write_text(OLD_ROUTING)
    (pi.dir / "routing.env.prev").write_text(OLDER_ROUTING)

    result = pi.tiles_seed()

    assert result.returncode == 0, result.stderr
    assert (pi.dir / "routing.env").read_text() == f"VALHALLA_TILESET={TILESET}\n"
    assert (pi.dir / "routing.env.prev").read_text() == OLD_ROUTING
    assert not [p for p in pi.dir.iterdir() if p.name.endswith(".orig") or ".tmp." in p.name]


def test_a_second_run_with_the_same_tileset_copies_nothing_and_says_unchanged(
    pi: FakePi, source: dict[str, bytes]
) -> None:
    assert pi.tiles_seed().returncode == 0
    (pi.dir / "routing.env.prev").write_text(OLDER_ROUTING)
    first_calls = len(pi.helper_runs())

    result = pi.tiles_seed()

    assert result.returncode == 0, result.stderr
    assert set(labels(pi)[first_calls:]) == {"source-sums", "tileset-exists", "tileset-sums", "stored-sums"}
    assert (pi.dir / "routing.env.prev").read_text() == OLDER_ROUTING  # the pointer did not change: no rotation
    assert [line["result"] for line in pi.tiles_log()] == ["ok", "unchanged"]
    assert "unchanged" in result.stderr


def test_an_existing_tileset_with_other_content_is_refused_not_overwritten(
    pi: FakePi, source: dict[str, bytes]
) -> None:
    other = tileset_dir(pi)
    other.mkdir(parents=True)
    for name in TILES_FILES:
        (other / name).write_bytes(b"something else\n")
    (pi.dir / "routing.env").write_text(OLD_ROUTING)

    result = pi.tiles_seed()

    assert result.returncode == 1
    assert f"tilesets/{TILESET} already holds different content" in result.stderr
    assert all((other / name).read_bytes() == b"something else\n" for name in TILES_FILES)
    assert (pi.dir / "routing.env").read_text() == OLD_ROUTING
    assert not mutating_compose(pi)
    assert pi.tiles_log()[-1]["result"] == "failed"


def test_a_copy_that_does_not_match_the_source_is_dropped_and_routing_env_stays(
    pi: FakePi, source: dict[str, bytes]
) -> None:
    (pi.dir / "routing.env").write_text(OLD_ROUTING)
    wrong = checksums(source).replace("a", "b", 1).replace("0", "1", 1)
    pi.rule("docker", "verify-copy", stdout=wrong + "\n")

    result = pi.tiles_seed()

    assert result.returncode == 1
    assert "checksum of the copy differs from the source" in result.stderr
    assert "drop-partial" in labels(pi) and "finalize-tileset" not in labels(pi)
    assert not tileset_dir(pi).exists() and not list((pi.volume / "tilesets").glob(".*partial"))
    assert (pi.dir / "routing.env").read_text() == OLD_ROUTING
    assert not mutating_compose(pi)


@pytest.mark.parametrize("missing", TILES_FILES)
def test_a_missing_source_file_is_named_and_nothing_is_touched(
    pi: FakePi, source: dict[str, bytes], missing: str
) -> None:
    (pi.spike / "custom_files" / missing).unlink()

    result = pi.tiles_seed()

    assert result.returncode == 1
    assert f"missing file {missing}" in result.stderr
    assert not pi.helper_runs() and not mutating_compose(pi) and not (pi.dir / "routing.env").exists()


def test_less_than_ten_gb_free_refuses_before_any_container_runs(pi: FakePi, source: dict[str, bytes]) -> None:
    pi.rule("df", stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 245000000 1 9000000 1% /\n")

    result = pi.tiles_seed()

    assert result.returncode == 1 and "disk: only" in result.stderr and "need 10 GB" in result.stderr
    assert not pi.helper_runs()


@pytest.mark.parametrize(
    "args",
    [("2026-11-01",), ("2026110",), ("abc",), ("",), (TILESET, "../other"), (TILESET, "/abs/path"), (TILESET, "a b"),
     (TILESET, "valhalla-spike/custom_files", "17x")],
)  # fmt: skip
def test_invalid_arguments_stop_with_exit_2_before_any_docker_call(
    pi: FakePi, source: dict[str, bytes], args: tuple[str, ...]
) -> None:
    result = pi.tiles_seed(*args)

    assert result.returncode == 2
    assert not pi.calls("docker")


@pytest.mark.parametrize("routing_before", [None, OLD_ROUTING])
@pytest.mark.parametrize("running_before", [False, True])
@pytest.mark.parametrize(
    ("rule", "reason"),
    [
        (
            {"args_contain": ["exec"], "stdout": '{"version":"3.9.1","tileset_last_modified":1700000000}'},
            "tileset_last_modified is '1700000000', expected 1793560782",
        ),
        (
            {"args_contain": ["exec"], "stdout": '{"version":"3.8.0","tileset_last_modified":1793560782}'},
            "version '3.8.0', expected 3.9.1",
        ),
        ({"args_contain": ["exec"], "exit": 1}, "/status did not answer"),
        ({"args_contain": ["up", "valhalla"], "exit": 1}, "did not become healthy"),
    ],
)
def test_a_failed_start_restores_routing_env_and_stops_valhalla_only_if_it_was_not_running(
    pi: FakePi,
    source: dict[str, bytes],
    rule: dict[str, Any],
    reason: str,
    running_before: bool,
    routing_before: str | None,
) -> None:
    if routing_before:
        (pi.dir / "routing.env").write_text(routing_before)
        (pi.dir / "routing.env.prev").write_text(OLDER_ROUTING)
    if running_before:
        pi.rule("docker", "ps", "service=valhalla", stdout="0123abcd\n")
    answer = {key: value for key, value in rule.items() if key != "args_contain"}
    pi.rule("docker", *rule["args_contain"], **answer)

    result = pi.tiles_seed()

    assert result.returncode == 1
    assert reason in result.stderr
    assert (pi.dir / "routing.env").exists() == bool(routing_before)
    if routing_before:
        assert (pi.dir / "routing.env").read_text() == routing_before
        assert (pi.dir / "routing.env.prev").read_text() == OLDER_ROUTING
    else:
        assert not (pi.dir / "routing.env.prev").exists()
    stops = [argv for argv in compose_verbs(pi) if "stop" in argv]
    assert bool(stops) is (not running_before)
    assert pi.tiles_log()[-1]["result"] == "failed" and reason in pi.tiles_log()[-1]["reason"]


def test_no_docker_call_touches_the_planner_or_anything_outside_project_overland(
    pi: FakePi, source: dict[str, bytes]
) -> None:
    (pi.dir / "routing.env").write_text(OLD_ROUTING)
    pi.rule("docker", "up", "valhalla", exit=1)  # also the failure path

    pi.tiles_seed()
    pi.tiles_seed()

    mutations = mutating_compose(pi)
    assert mutations
    for argv in mutations:
        assert argv[:3] == ["compose", "-p", "overland"], argv
        assert argv[-1] == "valhalla" and "planner" not in argv and "down" not in argv, argv
    for argv in (c["argv"] for c in pi.calls("docker")):
        assert argv[:1] in (["compose"], ["run"], ["ps"]), argv
