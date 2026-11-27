"""Steps 13-20 and 13-21: `scripts/road-map-runner.sh`, the timed job that takes the owner's request at its time,
validates it strictly, starts the refresh, retries a busy Pi, records what happened and recovers a rebuild the Pi lost
(D303, D304, D314, D315, D316). The clock is the seam ROAD_MAP_NOW (epoch seconds): one script run per simulated
minute. The real script runs under /bin/bash with the shims of
tests/deploy/shims (docker, flock, timeout; never the real ones); the changes folder is a real folder of the fake volume
`overland_road-map`. The refresh itself is replaced by a stub that records how it was called: its own behaviour is
tested in test_tiles_refresh_*.

Assertions are on what the changes folder holds, on the stub's record and on the argv of every docker and timeout call.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.deploy.conftest import FakePi

PREFIX = "https://download.geofabrik.de/"
ITALY = ("italy", "Italy", "", f"{PREFIX}europe/italy/italy-latest.osm.pbf", f"{PREFIX}europe/italy/italy.poly", "2200")
UTAH = (
    "us/utah",
    "Utah (Ütah)",
    "US",
    f"{PREFIX}north-america/us/utah/utah-latest.osm.pbf",
    f"{PREFIX}north-america/us/utah/utah.poly",
    "1100",
)
LONG_AGO = 1_700_000_000
FAR_AHEAD = 4_000_000_000
STUB = """#!/usr/bin/env bash
{ printf 'progress=%s\\n' "${ROAD_MAP_PROGRESS:-}"; printf 'mode=%s\\n' "$(ls -l "$REGIONS_FILE" | cut -c1-10)"
  printf 'cwd=%s\\n' "$PWD"; cat "$REGIONS_FILE"; } >"$PWD/refresh-call.txt"
volume="$SHIM_HOME/volumes/overland_road-map"
cat "$volume/running.txt" >"$PWD/running-during.txt"
[ -z "${STUB_FAILURE:-}" ] || printf '%b' "$STUB_FAILURE" >"$volume/failure.txt"
exit "${STUB_EXIT:-0}"
"""


def folder(pi: FakePi) -> Path:
    path = pi.shim_home / "volumes" / "overland_road-map"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stub_refresh(pi: FakePi) -> None:
    (pi.dir / "scripts" / "tiles-refresh.sh").write_text(STUB)


def request_text(
    regions: tuple[tuple[str, ...], ...] = (ITALY, UTAH), start_at: int | None = LONG_AGO, schema: str = "1"
) -> str:
    lines = [f"schema={schema}", "requested_at=1700000000"]
    if start_at is not None:
        lines.append(f"start_at={start_at}")
    lines += ["region=" + "\t".join(region) for region in regions]
    return "\n".join([*lines, "added=Italy, Utah", "removed="]) + "\n"


def put_request(pi: FakePi, text: str) -> None:
    (folder(pi) / "request.txt").write_text(text)


def run_runner(pi: FakePi, **env: str) -> subprocess.CompletedProcess[str]:
    return pi.run_script("road-map-runner.sh", env=env)


def refresh_record(pi: FakePi) -> str | None:
    path = pi.dir / "refresh-call.txt"
    return path.read_text() if path.exists() else None


def docker_runs(pi: FakePi) -> list[list[str]]:
    return [c["argv"] for c in pi.calls("docker") if c["argv"][:1] == ["run"]]


@pytest.mark.parametrize("start_at", [LONG_AGO, None], ids=["start time passed", "no start time"])
def test_a_due_request_is_taken_and_the_refresh_is_called_once_with_its_regions(
    pi: FakePi, start_at: int | None
) -> None:
    stub_refresh(pi)
    put_request(pi, request_text(start_at=start_at))

    result = run_runner(pi)

    assert result.returncode == 0, result.stderr
    assert (pi.dir / "running-during.txt").read_text() == request_text(start_at=start_at)
    assert not (folder(pi) / "request.txt").exists()
    assert refresh_record(pi) == (
        f"progress=on\nmode=-rw-------\ncwd={pi.dir.resolve()}\n"
        + "\n".join("\t".join(r) for r in (ITALY, UTAH))
        + "\n"
    )
    assert not list(pi.dir.glob(".road-map-regions*")), "the regions file is not left behind"


def test_a_rebuild_that_ended_well_leaves_a_result_with_the_request_copied(pi: FakePi) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())
    (folder(pi) / "progress.txt").write_text("step=switching\nstep_at=1800000000\nserving=20261101\nnew=20270201\n")

    run_runner(pi, STUB_EXIT="0")

    result = (folder(pi) / "result.txt").read_text().splitlines()
    assert re.fullmatch(r"finished_at=\d{10}", result[0]) and result[1] == "state=done"
    assert result[2:] == ["tileset=20270201", *request_text().splitlines()]
    assert not (folder(pi) / "running.txt").exists()


@pytest.mark.parametrize("quiet", ["no request", "start in the future"])
def test_the_helper_is_seen_on_every_run_and_a_request_not_yet_due_is_left_alone(pi: FakePi, quiet: str) -> None:
    stub_refresh(pi)
    future = request_text(start_at=FAR_AHEAD)
    if quiet != "no request":
        put_request(pi, future)

    run_runner(pi)

    assert (folder(pi) / "helper-seen").is_file()
    assert refresh_record(pi) is None
    assert sorted(p.name for p in folder(pi).iterdir()) == (
        ["helper-seen"] if quiet == "no request" else ["helper-seen", "request.txt"]
    )
    assert quiet == "no request" or (folder(pi) / "request.txt").read_text() == future


def mutated(old: str, new: str) -> str:
    return request_text().replace(old, new, 1)


BAD_REQUESTS = {
    "wrong schema": request_text(schema="2"),
    "a key that is not a key": mutated("us/utah", "Us/Utah"),
    "a key with a command": mutated("us/utah", "$(touch pwned)"),
    "an address outside the prefix": mutated(
        f"{PREFIX}europe/italy/italy-latest", "https://example.invalid/italy-latest"
    ),
    "an address with ..": mutated(f"{PREFIX}europe/italy/italy.poly", f"{PREFIX}europe/../italy/italy.poly"),
    "an address of another region": mutated("italy/italy-latest.osm.pbf", "utah/utah-latest.osm.pbf"),
    "a control character in a name": mutated("Utah", "Ut\x07ah"),
    "a name over 120 bytes": mutated("Utah", "U" * 121),
    "an oversized request": request_text() + "added=" + "x" * 70_000 + "\n",
    "41 regions": request_text(
        regions=tuple((f"r{i}", "R", "", f"{PREFIX}r{i}-latest.osm.pbf", f"{PREFIX}r{i}.poly", "1") for i in range(41))
    ),
    "a start time that is not a number": request_text(start_at=None).replace(
        "requested_at", "start_at=soon\nrequested_at", 1
    ),
    "a size that is not a number": mutated("2200", "22e2"),
    "a line the planner does not write": request_text() + "extra=1\n",
}


@pytest.mark.parametrize("text", BAD_REQUESTS.values(), ids=BAD_REQUESTS.keys())
def test_a_request_that_is_not_what_the_planner_writes_is_refused_and_nothing_runs(pi: FakePi, text: str) -> None:
    stub_refresh(pi)
    put_request(pi, text)

    run_runner(pi)

    result = (folder(pi) / "result.txt").read_text().splitlines()
    assert re.fullmatch(r"finished_at=\d{10}", result[0]) and result[1:] == ["state=failed", "code=bad_request"]
    assert refresh_record(pi) is None
    assert sorted(p.name for p in folder(pi).iterdir()) == ["helper-seen", "result.txt"]
    assert not (pi.root / "pwned").exists()


def make_link(pi: FakePi, path: Path) -> None:
    elsewhere = pi.root / "elsewhere.txt"
    elsewhere.write_text(request_text())
    path.symlink_to(elsewhere)


@pytest.mark.parametrize("kind", ["a link", "a folder", "a pipe"])
def test_a_request_that_is_not_a_plain_file_is_refused_and_never_read(pi: FakePi, kind: str) -> None:
    stub_refresh(pi)
    path = folder(pi) / "request.txt"
    {"a link": lambda: make_link(pi, path), "a folder": path.mkdir, "a pipe": lambda: os.mkfifo(path)}[kind]()

    result = run_runner(pi)

    assert result.returncode == 0, result.stderr
    assert "state=failed\ncode=bad_request" in (folder(pi) / "result.txt").read_text()
    assert refresh_record(pi) is None
    assert not path.exists() and not path.is_symlink()
    assert kind != "a link" or (pi.root / "elsewhere.txt").read_text() == request_text()


def test_an_address_under_a_prefix_the_pi_sets_in_its_env_is_taken(pi: FakePi) -> None:
    stub_refresh(pi)
    (pi.dir / ".env").write_text(
        (pi.dir / ".env").read_text() + "ROAD_MAP_DOWNLOAD_PREFIX=https://mirror.invalid/maps/\n"
    )
    mirrored = request_text().replace(PREFIX, "https://mirror.invalid/maps/")
    put_request(pi, mirrored)

    run_runner(pi)

    assert (pi.dir / "running-during.txt").read_text() == mirrored
    assert refresh_record(pi) is not None


def test_every_docker_call_of_the_helper_is_locked_down_and_never_names_the_served_map(pi: FakePi) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())
    run_runner(pi)

    runs = docker_runs(pi)
    assert len(runs) >= 4, "the helper looks, takes and writes through containers"
    for argv in runs:
        joined = " ".join(argv)
        for flag in (
            "--network none",
            "--user 10001:10001",
            "--cap-drop ALL",
            "--read-only",
            "--security-opt no-new-privileges",
        ):
            assert flag in joined, joined
        assert "--pids-limit" in joined and "--memory" in joined, joined
        assert "overland_valhalla-data" not in joined and "valhalla-data" not in joined, joined
        assert [a.split(":")[0] for a in argv if re.fullmatch(r"[\w-]+:/\w+", a)] == ["overland_road-map"], joined


def test_every_docker_run_of_the_helper_is_wrapped_in_timeout_60(pi: FakePi) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())
    run_runner(pi)

    timeouts = [c["argv"] for c in pi.calls("timeout")]
    assert len(docker_runs(pi)) >= 4
    assert [argv[:3] for argv in timeouts] == [["60", "docker", "run"]] * len(docker_runs(pi))


def test_a_request_cancelled_just_before_the_helper_takes_it_is_not_started(pi: FakePi) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())
    pi.rule("docker", "take-request", stdout="gone\n")  # the planner's rename won: there is no request.txt to take

    result = run_runner(pi)

    assert result.returncode == 0, result.stderr
    assert refresh_record(pi) is None
    assert not (folder(pi) / "result.txt").exists() and not (folder(pi) / "running.txt").exists()


@contextlib.contextmanager
def hold(pi: FakePi, name: str) -> Iterator[None]:
    with (pi.dir / name).open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def test_a_request_is_not_taken_while_a_rebuild_is_recorded_as_running(pi: FakePi) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())
    (folder(pi) / "running.txt").write_text("schema=1\n")

    with hold(pi, ".deploy.lock"):  # a deploy runs: the rebuild recorded as running is not looked at (step 13-21)
        run_runner(pi)

    assert refresh_record(pi) is None
    assert (folder(pi) / "request.txt").read_text() == request_text()
    assert (folder(pi) / "running.txt").read_text() == "schema=1\n"


def test_a_second_helper_at_the_same_time_leaves_without_reading_the_request(pi: FakePi) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())
    with (pi.dir / ".road-map-runner.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_runner(pi)

    assert result.returncode == 0, result.stderr
    assert refresh_record(pi) is None and (folder(pi) / "request.txt").exists()
    assert (folder(pi) / "helper-seen").exists(), "the heartbeat is touched before the lock is looked at"


# ---- step 13-21: retries, results, recovery, the log --------------------------------------------------

T0 = 1_800_000_000
MINUTE = 60
LOCKED_AFTER = 30 * MINUTE


def minute(pi: FakePi, n: int, **env: str) -> subprocess.CompletedProcess[str]:
    """One run of the helper at the n-th simulated minute (the clock is the seam ROAD_MAP_NOW)."""
    return run_runner(pi, ROAD_MAP_NOW=str(T0 + n * MINUTE), **env)


def result_lines(pi: FakePi) -> list[str]:
    return (folder(pi) / "result.txt").read_text().splitlines()


def log_lines(pi: FakePi) -> list[str]:
    path = pi.dir / "road-map-runner.log"
    return path.read_text().splitlines() if path.exists() else []


def test_a_refresh_that_finds_the_pi_busy_is_retried_each_minute_for_half_an_hour_then_fails_as_locked(
    pi: FakePi,
) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())

    for n in range(30):  # minutes 0..29: 75 each time, the request is back, nothing is written about a failure
        minute(pi, n, STUB_EXIT="75")
        assert (folder(pi) / "request.txt").read_text() == request_text(), n
        assert not (folder(pi) / "running.txt").exists() and not (folder(pi) / "result.txt").exists(), n
    assert (folder(pi) / "locked-since.txt").read_text().strip() == str(T0)

    minute(pi, 30, STUB_EXIT="75")  # the Pi was busy for 30 minutes

    assert result_lines(pi)[1:] == ["state=failed", "code=locked", *request_text().splitlines()]
    assert sorted(p.name for p in folder(pi).iterdir()) == ["helper-seen", "result.txt"]


FAILURES = {
    "disk with its numbers": ("code=disk\nfree_gb=12\nneed_gb=40\n", ["code=disk", "free_gb=12", "need_gb=40"]),
    "memory with its number": ("code=memory\nhave_gb=3\n", ["code=memory", "have_gb=3"]),
    "no failure note": ("", ["code=interrupted"]),
    "a note that is not what the refresh writes": ("code=disk\nfree_gb=lots\n", ["code=interrupted"]),
    "a note with a free-text line": ("code=build\nreason=$(touch pwned)\n", ["code=interrupted"]),
}


@pytest.mark.parametrize("note, expected", FAILURES.values(), ids=FAILURES.keys())
def test_a_refresh_that_fails_leaves_its_code_and_numbers_and_keeps_the_request_lines(
    pi: FakePi, note: str, expected: list[str]
) -> None:
    stub_refresh(pi)
    put_request(pi, request_text())
    (folder(pi) / "locked-since.txt").write_text(f"{T0}\n")  # an earlier busy minute is forgotten by any other end

    minute(pi, 5, STUB_EXIT="1", STUB_FAILURE=note)

    lines = result_lines(pi)
    assert re.fullmatch(r"finished_at=\d{10}", lines[0]) and lines[1] == "state=failed"
    assert lines[2:] == [*expected, *request_text().splitlines()]
    assert sorted(p.name for p in folder(pi).iterdir()) == ["helper-seen", "result.txt"]
    assert not (pi.root / "pwned").exists()


def test_two_helpers_in_the_same_minute_leave_every_file_but_the_heartbeat_as_it_was(pi: FakePi) -> None:
    stub_refresh(pi)
    (folder(pi) / "running.txt").write_text(request_text())
    before = {p.name: p.read_text() for p in folder(pi).iterdir()}

    with hold(pi, ".road-map-runner.lock"):
        result = minute(pi, 1)

    after = {p.name: p.read_text() for p in folder(pi).iterdir() if p.name != "helper-seen"}
    assert result.returncode == 0 and after == before
    assert pi.calls("docker") and all(c["argv"][:1] == ["run"] for c in pi.calls("docker")), "only the heartbeat ran"
    assert log_lines(pi) == []


def lost_rebuild(pi: FakePi, serving: str, building: str = "20270201") -> None:
    (folder(pi) / "running.txt").write_text(request_text())
    (folder(pi) / "progress.txt").write_text(
        f"step=switching\nstep_at={T0}\nserving=20261101\nnew={building}\nbuild_started_at={T0}\n"
    )
    (pi.dir / "routing.env").write_text(f"VALHALLA_TILESET={serving}\n")


def compose_calls(pi: FakePi) -> list[list[str]]:
    return [c["argv"] for c in pi.calls("docker") if c["argv"][:1] == ["compose"]]


@pytest.mark.parametrize(
    "serving, expected",
    [("20270201", ["state=done"]), ("20261101", ["state=failed", "code=interrupted"])],
    ids=["after the switch: done", "before the switch: interrupted, the old map serves"],
)
def test_a_rebuild_nobody_holds_is_decided_by_the_map_routing_env_names(
    pi: FakePi, serving: str, expected: list[str]
) -> None:
    stub_refresh(pi)
    lost_rebuild(pi, serving)

    minute(pi, 1)

    named = ["tileset=20270201"] if expected == ["state=done"] else []
    assert result_lines(pi)[1:] == [*expected, *named, *request_text().splitlines()]
    assert sorted(p.name for p in folder(pi).iterdir()) == ["helper-seen", "progress.txt", "result.txt"]
    assert (pi.dir / "routing.env").read_text() == f"VALHALLA_TILESET={serving}\n", "recovery never moves a pointer"
    up = [argv for argv in compose_calls(pi) if "up" in argv and "valhalla" in argv]
    assert len(up) == 1 and refresh_record(pi) is None
    assert next(c["argv"][:4] for c in pi.calls("timeout") if c["argv"][2:3] == ["compose"]) == [
        "120",
        "docker",
        "compose",
        "-p",
    ]


def test_a_rebuild_the_pi_lost_is_not_touched_while_a_deploy_holds_the_lock_and_is_decided_the_next_minute(
    pi: FakePi,
) -> None:
    stub_refresh(pi)
    lost_rebuild(pi, "20270201")
    before = {p.name for p in folder(pi).iterdir()}

    with hold(pi, ".deploy.lock"):
        minute(pi, 1)
    assert {p.name for p in folder(pi).iterdir()} == before | {"helper-seen"}
    assert compose_calls(pi) == [] and log_lines(pi) == []

    minute(pi, 2)
    assert result_lines(pi)[1] == "state=done"


def test_a_rebuild_whose_engine_does_not_answer_is_left_for_the_next_minute(pi: FakePi) -> None:
    stub_refresh(pi)
    lost_rebuild(pi, "20270201")
    pi.rule("docker", "exec", exit=1)

    minute(pi, 1, ROAD_MAP_POLL="0")

    assert not (folder(pi) / "result.txt").exists() and (folder(pi) / "running.txt").exists()


def test_the_log_gains_a_line_per_state_change_never_for_an_idle_minute_and_is_cut_to_200_lines_past_64_kb(
    pi: FakePi,
) -> None:
    stub_refresh(pi)
    minute(pi, 0)
    assert log_lines(pi) == [], "an idle minute writes nothing"

    put_request(pi, request_text())
    minute(pi, 1, STUB_EXIT="75")
    minute(pi, 2, STUB_EXIT="1", STUB_FAILURE="code=build\n")
    put_request(pi, request_text())
    (folder(pi) / "progress.txt").write_text(f"step=switching\nstep_at={T0}\nserving=1\nnew=20270201\n")
    minute(pi, 3)
    assert [line.split(" ", 1)[1] for line in log_lines(pi)] == [
        "taken", "busy", "taken", "failed code=build", "taken", "done",
    ]  # fmt: skip
    assert all(line.split(" ", 1)[0].isdigit() for line in log_lines(pi))

    (pi.dir / "road-map-runner.log").write_text("".join(f"{T0} old line {i:04d} {'x' * 60}\n" for i in range(1000)))
    lost_rebuild(pi, "20270201")  # one state change, so the cut leaves exactly the last 200 lines
    minute(pi, 4)

    lines = log_lines(pi)
    assert len(lines) == 200 and lines[-1].endswith(" recovered done") and "old line 0999" in lines[-2]
    assert (pi.dir / "road-map-runner.log").stat().st_size < 65536
