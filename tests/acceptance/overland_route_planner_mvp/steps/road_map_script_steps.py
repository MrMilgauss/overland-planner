"""Slice 12c steps for the shell side (D303, D304, D313, D314): the helper that takes the owner's request on the Pi
and the refresh script it runs. The real scripts run under /bin/bash with the offline seams of tests/deploy (shims
for docker, crontab, flock, df, curl; the fake Pi folder `FakePi`), exactly as the D277 refresh tests; the real
refresh (about an hour) is never run offline.

No production module is imported. The scripts are `deploy/scripts/road-map-helper.sh` (install | uninstall | status)
and `deploy/scripts/road-map-runner.sh` (the cron job: one run a minute). Until DELIVER writes them `FakePi` does
not copy them and `bash` answers "No such file": the Thens fail on what the Pi holds after the run (no timed job, no
result), a business reason, not on an import.

Mandate 8: every step that changes the Pi's timed jobs or the changes folder compares a view of port-visible names
(`schedule.helper_lines`, `schedule.other_lines`, `queue.files`, `pi.served_map`, `pi.refresh_calls`) before and after
with `assert_state_delta`; the file names are the helper's side of the changes folder, the port of the helper.

PINs (DESIGN names the facts, DISTILL fixes the spelling; DELIVER may change a PIN with its script in the same
commit): the regions file given to the refresh has one region per line, six tab-separated fields (key, name, parent
name, .osm.pbf address, .poly address, bytes), as D313 says; the progress hook is a helper-container run labelled
`progress` whose next argument is the step; the queue volume is `overland_road-map`; `progress.txt` carries
`new=<tileset>` (D314).

Shared test constants: `FakePi`, `TILES_FILES`, `REFRESH_DATE` and the shim environment are imported from
tests/deploy/conftest.py rather than moved to a shared module (a move would touch every deploy test file; left as is).
"""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pytest_bdd import given, parsers, then, when

from tests.acceptance.overland_route_planner_mvp.steps.road_map_fakes import (
    EIGHT,
    GB,
    SIZES_GB,
    catalogue_features,
    feature_by_key,
)
from tests.acceptance.overland_route_planner_mvp.steps.world import PlannerWorld
from tests.common.state_delta import assert_state_delta, unchanged
from tests.deploy.conftest import NEW, REFRESH_DATE, TILES_FILES, FakePi, shim_env
from tests.deploy.test_makefile_targets import PURGE_WORD, remote

MARKER = "# overland-road-map-runner"
BACKUP = "30 3 * * * /usr/local/bin/backup-home --quiet"
COMMENT = "# nightly jobs"
SERVED, KEPT, OLDER = "20261101", "20260901", "20260801"
NEW_MAP = REFRESH_DATE  # 20270201: the map the refresh makes on the pinned UTC date
LOCK_REFUSAL = 75
GOOD_ADDRESS = "https://download.geofabrik.de/"
SCHEDULE = {"schedule.helper_lines", "schedule.other_lines"}
PI = {"queue.files", "pi.served_map", "pi.refresh_calls"}


def pi_of(world: PlannerWorld) -> FakePi:
    pi = world.scratch.get("pi")
    assert isinstance(pi, FakePi), "this scenario has no Pi"
    return pi


def make_pi(world: PlannerWorld, *, spaced: bool = False) -> FakePi:
    if "pi" not in world.scratch:
        world.scratch["pi"] = FakePi(world.tmp_path / ("my pi" if spaced else "pi"))
    return pi_of(world)


def schedule_file(pi: FakePi) -> Path:
    return pi.shim_home / "crontab.txt"


def schedule_lines(pi: FakePi) -> list[str]:
    path = schedule_file(pi)
    return path.read_text().splitlines() if path.exists() else []


def ours_line(pi: FakePi) -> str:
    return f"* * * * * cd '{pi.dir}' && bash scripts/road-map-runner.sh >>road-map-runner.log 2>&1 {MARKER}"


def queue_dir(pi: FakePi) -> Path:
    path = pi.shim_home / "volumes" / "overland_road-map"
    path.mkdir(parents=True, exist_ok=True)
    return path


def compose_mutations(pi: FakePi) -> list[list[str]]:
    return [
        c["argv"] for c in pi.calls("docker") if c["argv"][:1] == ["compose"] and {"run", "stop", "up"} & set(c["argv"])
    ]


def served_map(pi: FakePi) -> str:
    path = pi.dir / "routing.env"
    return path.read_text().strip() if path.exists() else ""


def snapshot(pi: FakePi) -> dict[str, Any]:
    """What the Pi shows through its ports: the timed jobs, the changes folder, the served map, the refresh's calls."""
    lines = schedule_lines(pi)
    return {
        "schedule.helper_lines": tuple(line for line in lines if MARKER in line),
        "schedule.other_lines": tuple(line for line in lines if MARKER not in line),
        "queue.files": tuple(sorted(p.name for p in queue_dir(pi).iterdir())),
        "pi.served_map": served_map(pi),
        "pi.refresh_calls": tuple(" ".join(a) for a in compose_mutations(pi)),
    }


def predicate(name: str, check: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    check.__name__ = name
    return check


def files_after(*present: str, absent: tuple[str, ...] = ()) -> Callable[[Any, Any], bool]:
    return predicate(
        f"queue.files holds {present} and not {absent}",
        lambda _old, new: all(n in new for n in present) and not any(n in new for n in absent),
    )


ANY = predicate("any", lambda _old, _new: True)


def settled(world: PlannerWorld, queue: Any = ANY, served: Any = ANY, calls: Any = ANY) -> None:
    """Mandate 8: the changes folder, served map and refresh calls before and after the When; `unchanged()` is strict."""  # noqa: E501
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        PI,
        {"queue.files": queue, "pi.served_map": served, "pi.refresh_calls": calls},
    )


def run_in_install(pi: FakePi, *command: str, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """`cd <install dir> && bash scripts/...` as cron and make run it: the install folder is the working folder."""
    meminfo = pi.root / "meminfo"
    meminfo.write_text("MemTotal:       16000000 kB\nMemAvailable:   12582912 kB\n")
    environment = {"TILES_DATE": REFRESH_DATE, "MEMINFO": str(meminfo), **(extra or {})}
    return subprocess.run(
        ["bash", *command],
        cwd=pi.dir,
        env=shim_env(pi.shim_home, HOME=str(pi.root), **environment),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def run_and_compare(world: PlannerWorld, *command: str, extra: dict[str, str] | None = None) -> None:
    pi = pi_of(world)
    world.scratch["schedule_text_before"] = schedule_file(pi).read_text() if schedule_file(pi).exists() else ""
    world.scratch["before"] = snapshot(pi)
    result = run_in_install(pi, *command, extra=extra)
    world.scratch["run"] = result
    world.scratch["after"] = snapshot(pi)
    release_locks(world)


def release_locks(world: PlannerWorld) -> None:
    for holder in world.scratch.pop("held", []):
        holder.close()


# ----------------------------------------------------------------------------------------------- the timed jobs
@given("a Pi that runs no jobs of its own")
def given_no_timed_jobs(world: PlannerWorld) -> None:
    make_pi(world)


@given("a Pi whose app folder has a space in its name and which runs no jobs of its own")
def given_a_spaced_install_folder(world: PlannerWorld) -> None:
    make_pi(world, spaced=True)


@given("a Pi with a nightly backup and a note")
def given_backup_and_comment(world: PlannerWorld) -> None:
    pi = make_pi(world)
    schedule_file(pi).write_text(f"{COMMENT}\n{BACKUP}\n")


@given("a Pi with a nightly backup and the road-map helper")
def given_backup_and_helper(world: PlannerWorld) -> None:
    pi = make_pi(world)
    schedule_file(pi).write_text(f"{BACKUP}\n{ours_line(pi)}\n")


@given("a Pi with a nightly backup and a note, and an older road-map helper")
def given_backup_comment_and_helper(world: PlannerWorld) -> None:
    pi = make_pi(world)
    older = (
        f"*/5 * * * * cd {pi.dir} && bash scripts/road-map-runner.sh {MARKER}"  # every five minutes, path not quoted
    )
    schedule_file(pi).write_text(f"{COMMENT}\n{BACKUP}\n{older}\n")


@given("a Pi with a nightly backup whose jobs cannot be read for a reason other than having none")
def given_an_unreadable_schedule(world: PlannerWorld) -> None:
    pi = make_pi(world)
    schedule_file(pi).write_text(f"{BACKUP}\n")
    pi.rule("crontab", "-l", exit=1, stderr="crontab: cannot read the list of timed jobs: Permission denied\n")


@given("a Pi whose jobs cannot be changed")
def given_a_schedule_that_cannot_be_written(world: PlannerWorld) -> None:
    pi = make_pi(world)
    pi.rule("crontab", exit=1, stderr="crontab: installing new crontab failed\n")


@when("the helper is installed")
def when_the_helper_is_installed(world: PlannerWorld) -> None:
    run_and_compare(world, "scripts/road-map-helper.sh", "install")


@when("the helper is uninstalled")
def when_the_helper_is_uninstalled(world: PlannerWorld) -> None:
    run_and_compare(world, "scripts/road-map-helper.sh", "uninstall")


@when("the helper is asked whether it is installed")
def when_the_helper_is_asked(world: PlannerWorld) -> None:
    run_and_compare(world, "scripts/road-map-helper.sh", "status")


def one_job_of(pi: FakePi) -> Callable[[Any, Any], bool]:
    return predicate(
        "exactly one timed job, run every minute from the quoted install folder",
        lambda _old, new: (
            len(new) == 1
            and new[0].startswith(f"* * * * * cd '{pi.dir}' && bash scripts/road-map-runner.sh")
            and new[0].endswith(MARKER)
        ),
    )


@then(parsers.re(r"the Pi runs the road-map helper every minute(?:, whatever the folder's name)?"))
def then_one_job_every_minute(world: PlannerWorld) -> None:
    pi = pi_of(world)
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        SCHEDULE,
        {"schedule.helper_lines": one_job_of(pi), "schedule.other_lines": unchanged()},
    )


@then("nothing in it names a host, a user or an address")
def then_the_job_names_no_one(world: PlannerWorld) -> None:
    pi = pi_of(world)
    lines = world.scratch["after"]["schedule.helper_lines"]
    assert len(lines) == 1, f"the Pi has {len(lines)} timed jobs for the helper"
    line = lines[0]
    assert not re.search(r"@|\b\d{1,3}(?:\.\d{1,3}){3}\b|ssh ", line), line
    assert re.findall(r"(?<![\w.])/[\w./ -]+", line.replace(str(pi.dir), "")) == [], (
        line
    )  # no path but the install folder


@then("the Pi runs the road-map helper every minute and keeps its backup and its note exactly")
def then_one_job_and_the_others_are_kept(world: PlannerWorld) -> None:
    pi = pi_of(world)
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        SCHEDULE,
        {"schedule.helper_lines": one_job_of(pi), "schedule.other_lines": unchanged()},
    )
    assert len(world.scratch["after"]["schedule.other_lines"]) >= 1


@then("the Pi's earlier jobs are saved before the change")
def then_the_old_list_is_saved(world: PlannerWorld) -> None:
    before = world.scratch["schedule_text_before"]
    saved = [p for p in pi_of(world).dir.iterdir() if p.is_file() and p.read_text(errors="ignore") == before]
    assert saved, (
        f"no file of the install folder holds the old list: {sorted(p.name for p in pi_of(world).dir.iterdir())}"
    )


@then("the Pi keeps its backup and no longer runs the road-map helper")
def then_only_the_backup_stays(world: PlannerWorld) -> None:
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        SCHEDULE,
        {
            "schedule.helper_lines": predicate("no helper line", lambda _o, new: new == ()),
            "schedule.other_lines": unchanged(),
        },
    )


@then("the Pi's jobs are exactly as they were")
def then_the_timed_jobs_are_as_they_were(world: PlannerWorld) -> None:
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        SCHEDULE,
        {"schedule.helper_lines": unchanged(), "schedule.other_lines": unchanged()},
    )
    assert world.scratch["after"]["schedule.other_lines"] == (BACKUP,), world.scratch["after"]


@then("the helper says it did not install")
def then_the_helper_did_not_install(world: PlannerWorld) -> None:
    result = world.scratch["run"]
    said = (result.stdout + result.stderr).lower()
    assert result.returncode != 0 and "not install" in said, f"exit {result.returncode}: {said[-200:]}"


@then(parsers.re(r"the helper answers that it is (?P<state>installed|not installed)"))
def then_the_helper_answers(world: PlannerWorld, state: str) -> None:
    result = world.scratch["run"]
    said = (result.stdout + result.stderr).lower()
    assert (result.returncode == 0) is (state == "installed"), f"exit {result.returncode}: {said[-200:]}"
    assert ("not installed" in said) is (state == "not installed") and "installed" in said, said[-200:]


@when("a release is deployed")
def when_a_release_is_deployed(world: PlannerWorld) -> None:
    world.scratch["deploy_result"] = pi_of(world).deploy(NEW.digest)


@then("the deploy ends well with one warning that the helper was not installed")
def then_the_deploy_warns_once(world: PlannerWorld) -> None:
    result = world.scratch["deploy_result"]
    assert result.returncode == 0, result.stderr
    warnings = [
        line for line in result.stderr.splitlines() if "helper" in line.lower() and "not installed" in line.lower()
    ]
    assert len(warnings) == 1, f"expected one warning about the helper, found {warnings}"


@then("the release is recorded")
def then_the_release_is_recorded(world: PlannerWorld) -> None:
    last = pi_of(world).releases_log()[-1]
    assert last["action"] == "deploy" and last["result"] == "ok", last


@when("the owner asks to purge the Pi's data")
def when_the_owner_asks_to_purge(world: PlannerWorld) -> None:
    pi = pi_of(world)
    pi.rule("docker", "volume ls", stdout="overland_planner-data\noverland_valhalla-data\n")
    world.scratch["before"] = snapshot(pi)
    world.scratch["purge"] = remote(pi, "purge", stdin=PURGE_WORD + "\n")
    world.scratch["after"] = snapshot(pi)


@then("the helper stops running before anything else is removed")
def then_the_job_goes_first(world: PlannerWorld) -> None:
    pi = pi_of(world)
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        SCHEDULE,
        {
            "schedule.helper_lines": predicate("no helper line", lambda _o, new: new == ()),
            "schedule.other_lines": unchanged(),
        },
    )
    calls = pi.calls()
    first_job = next((i for i, c in enumerate(calls) if c["tool"] == "crontab"), None)
    first_removal = next(
        (i for i, c in enumerate(calls) if c["tool"] == "docker" and c["argv"][:2] == ["volume", "rm"]), None
    )
    assert first_job is not None and first_removal is not None and first_job < first_removal, (first_job, first_removal)


# ------------------------------------------------------------------------------------------------ requests and runs
def serve(pi: FakePi) -> None:
    (pi.dir / "routing.env").write_text(f"VALHALLA_TILESET={SERVED}\n")
    (pi.dir / "routing.env.prev").write_text(f"VALHALLA_TILESET={KEPT}\n")
    for name in (SERVED, KEPT, OLDER):
        folder = pi.volume / "tilesets" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "valhalla_tiles.tar").write_text(f"tiles {name}\n")
        (folder / "timezones.sqlite").write_text(f"time zones of {name}\n")
    (pi.shim_home / "status_by_tileset.json").write_text(json.dumps({SERVED: "1790000000", NEW_MAP: "1793560782"}))


def region_fields(key: str, size_gb: float | None = None) -> list[str]:
    props = feature_by_key(key)["properties"]
    parent = next((f for f in catalogue_features() if f["properties"]["id"] == props["parent"]), None)
    size = int((size_gb if size_gb is not None else SIZES_GB[key]) * GB)
    return [
        key,
        props["name"],
        parent["properties"]["name"] if parent else "",
        props["urls"]["pbf"],  # the index's own addresses (D315)
        props["urls"]["poly"],
        str(size),
    ]


def write_request(
    pi: FakePi, *, start_at: int | str | None = None, fault: str | None = None, target: Path | None = None
) -> None:
    keys = [*EIGHT, "portugal"]
    lines = ["schema=1", f"requested_at={int(datetime.now(UTC).timestamp())}"]
    if start_at is not None:
        lines.append(f"start_at={start_at}")
    regions = [region_fields(k) for k in keys]
    if fault == "a region address on another host":
        regions[0][3] = regions[0][3].replace(GOOD_ADDRESS, "https://example.invalid/", 1)
    elif fault == "a region address that belongs to another region":
        regions[0][3] = regions[1][3]
    elif fault == "a region name that goes up a level":
        regions[0][0] = "italy/../etc"
    elif fault == "a size that is not a number":
        regions[0][5] = "12abc"
    elif fault == "forty-one regions":
        regions = [regions[i % len(regions)] for i in range(41)]
    elif fault == "a start time that is not a number":
        lines = [line for line in lines if not line.startswith("start_at=")] + ["start_at=tomorrow"]
    elif fault == "a command hidden in a region line":
        regions[0][0] = "$(touch pwned)"
    lines += [f"region={chr(9).join(r)}" for r in regions] + ["added=Portugal", "removed="]
    (target or queue_dir(pi) / "request.txt").write_text("\n".join(lines) + "\n")


def hours_ahead(hours: int) -> int:
    return int((datetime.now(UTC) + timedelta(hours=hours)).timestamp())


@given("a Pi serving the map of 1 November and a request adding Portugal whose start time has come")
def given_a_request_due(world: PlannerWorld) -> None:
    pi = make_pi(world)
    serve(pi)
    write_request(pi)
    # valhalla-fetch leaves the borders it downloaded in the meta folder of the volume (D314); the shim stands for it
    pi.rule(
        "docker",
        "valhalla-fetch",
        write={f"road-map-meta/outlines/{key.replace('/', '-')}.poly": f"{key}\n" for key in (*EIGHT, "portugal")},
        passthrough=True,
        times=1,
    )


@given("a Pi serving the map of 1 November and a request adding Portugal to start in 3 hours")
def given_a_request_not_yet_due(world: PlannerWorld) -> None:
    pi = make_pi(world)
    serve(pi)
    write_request(pi, start_at=hours_ahead(3))


@given(parsers.re(r"a Pi serving the map of 1 November and a request with (?P<fault>.+)"))
def given_a_faulty_request(world: PlannerWorld, fault: str) -> None:
    pi = make_pi(world)
    serve(pi)
    if fault == "a link in place of the request":
        elsewhere = pi.root / "elsewhere.txt"
        write_request(pi, target=elsewhere)
        world.scratch["elsewhere"] = elsewhere.read_text()
        (queue_dir(pi) / "request.txt").symlink_to(elsewhere)
        return
    write_request(pi, fault=fault)


@given("a Pi serving the map of 1 November and a request that the owner cancelled a moment ago")
def given_a_cancelled_request(world: PlannerWorld) -> None:
    pi = make_pi(world)
    serve(pi)
    write_request(pi)
    (queue_dir(pi) / "request.txt").rename(queue_dir(pi) / "cancelled.txt")


@given("a Pi serving the map of 1 November and a rebuild that the helper is still running")
def given_a_rebuild_still_running(world: PlannerWorld) -> None:
    pi = make_pi(world)
    serve(pi)
    write_request(pi)
    (queue_dir(pi) / "request.txt").rename(queue_dir(pi) / "running.txt")
    holder = (pi.dir / ".road-map-runner.lock").open("w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    world.scratch["held"] = [holder]


def lost_rebuild(world: PlannerWorld, serving: str) -> FakePi:
    pi = make_pi(world)
    serve(pi)
    write_request(pi)
    (queue_dir(pi) / "request.txt").rename(queue_dir(pi) / "running.txt")
    (queue_dir(pi) / "progress.txt").write_text(
        f"step=switching\nstep_at={int(datetime.now(UTC).timestamp())}\nserving={SERVED}\nnew={NEW_MAP}\n"
    )
    (pi.volume / "tilesets" / NEW_MAP).mkdir(parents=True, exist_ok=True)
    (pi.volume / "tilesets" / NEW_MAP / "valhalla_tiles.tar").write_text("new tiles\n")
    (pi.dir / "routing.env").write_text(f"VALHALLA_TILESET={serving}\n")
    return pi


@given("a Pi serving the map of 1 November that lost power during a rebuild making the map of 1 February 2027")
def given_a_rebuild_lost_before_the_switch(world: PlannerWorld) -> None:
    lost_rebuild(world, SERVED)


@given("a Pi serving the map of 1 February 2027 that lost power right after a rebuild made it")
def given_a_rebuild_lost_after_the_switch(world: PlannerWorld) -> None:
    lost_rebuild(world, NEW_MAP)


@given("a deploy is running on the Pi")
def given_a_deploy_is_running(world: PlannerWorld) -> None:
    pi = pi_of(world)
    holder = (pi.dir / ".deploy.lock").open("w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    world.scratch.setdefault("held", []).append(holder)


@given(parsers.re(r"the Pi has (?P<gb>\d+) GB of free disk"))
def given_the_pi_has_free_disk(world: PlannerWorld, gb: str) -> None:
    kilobytes = int(gb) * 1024 * 1024
    table = (
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        f"/dev/nvme0n1p2 245000000 {245000000 - kilobytes} {kilobytes} 92% /\n"
    )
    pi_of(world).rule("df", stdout=table)


@when("the helper runs")
def when_the_helper_runs(world: PlannerWorld) -> None:
    run_and_compare(world, "scripts/road-map-runner.sh")


def result_text(pi: FakePi) -> str:
    path = queue_dir(pi) / "result.txt"
    return path.read_text() if path.exists() else ""


def helper_looked(pi: FakePi) -> None:
    """A run of the helper touches `helper-seen` every time (D303): a script that is missing must not look like a quiet one."""  # noqa: E501
    assert (queue_dir(pi) / "helper-seen").exists(), "the helper did not run"


@then("the rebuild ran on the regions of the request, not on the old list of eight")
def then_the_refresh_ran_on_the_request(world: PlannerWorld) -> None:
    pi = pi_of(world)
    fetches = [a for a in compose_mutations(pi) if "valhalla-fetch" in a and "osmium merge" not in " ".join(a)]
    assert len(fetches) == 1, f"the refresh downloaded {len(fetches)} times: {world.scratch['run'].stderr[-400:]}"
    joined = " ".join(fetches[0])
    assert "portugal/portugal-latest.osm.pbf" in joined, "the request's region was not downloaded"
    assert len(set(re.findall(r"src/\d+\.osm\.pbf", joined))) == 9, (
        f"the nine regions were not each numbered: {joined[:300]}"
    )


@then("the request was taken and the rebuild ended well")
def then_the_request_was_taken(world: PlannerWorld) -> None:
    pi = pi_of(world)
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        PI,
        {
            "queue.files": files_after("result.txt", absent=("request.txt",)),
            "pi.served_map": predicate("any", lambda _o, _n: True),
            "pi.refresh_calls": predicate("the refresh ran", lambda _o, new: len(new) > 0),
        },
    )
    assert "state=done" in result_text(pi), result_text(pi)
    assert f"tileset={NEW_MAP}" in result_text(pi).splitlines(), result_text(pi)


@then("nothing was started and the request is still waiting")
def then_nothing_started_request_waits(world: PlannerWorld) -> None:
    helper_looked(pi_of(world))
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        PI,
        {
            "queue.files": files_after("request.txt", "helper-seen", absent=("running.txt", "result.txt")),
            "pi.served_map": unchanged(),
            "pi.refresh_calls": unchanged(),
        },
    )


@then("nothing was started")
def then_nothing_was_started(world: PlannerWorld) -> None:
    pi = pi_of(world)
    helper_looked(pi)
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        PI,
        {
            "queue.files": predicate("any", lambda _o, _n: True),
            "pi.served_map": unchanged(),
            "pi.refresh_calls": unchanged(),
        },
    )


@then("nothing was started and no result was written")
def then_nothing_started_no_result(world: PlannerWorld) -> None:
    helper_looked(pi_of(world))
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        PI,
        {
            "queue.files": files_after("helper-seen", absent=("result.txt",)),
            "pi.served_map": unchanged(),
            "pi.refresh_calls": unchanged(),
        },
    )


@then("the result says the request was not valid")
def then_the_request_was_not_valid(world: PlannerWorld) -> None:
    settled(world, queue=files_after("result.txt", absent=("running.txt",)), served=unchanged(), calls=unchanged())
    pi = pi_of(world)
    text = result_text(pi)
    assert "state=failed" in text and "code=bad_request" in text, text
    assert not (pi.root / "pwned").exists() and not (pi.dir / "pwned").exists(), "a hidden command ran"
    if "elsewhere" in world.scratch:
        assert (pi.root / "elsewhere.txt").read_text() == world.scratch["elsewhere"], "the linked file was changed"


@then("the helper acted as an ordinary user with no extra rights, and could not reach the internet or the served map")
def then_the_helper_containers_are_locked_down(world: PlannerWorld) -> None:
    settled(world)
    runs = [
        c["argv"]
        for c in pi_of(world).calls("docker")
        if c["argv"][:1] == ["run"] and "overland_road-map" in " ".join(c["argv"])
    ]
    assert runs, f"the helper started no container for the changes: {world.scratch['run'].stderr[-300:]}"
    for argv in runs:
        joined = " ".join(argv)
        assert "--user 10001:10001" in joined and "--network none" in joined and "--cap-drop ALL" in joined, joined
        assert "overland_valhalla-data" not in joined, joined


@then("the request is waiting again and no result was written")
def then_the_request_waits_again(world: PlannerWorld) -> None:
    settled(
        world, queue=files_after("request.txt", absent=("running.txt", "result.txt")), served=unchanged(), calls=ANY
    )
    pi = pi_of(world)
    helper_looked(pi)
    assert (queue_dir(pi) / "request.txt").exists() and not (queue_dir(pi) / "running.txt").exists()
    assert result_text(pi) == ""


@then("the second run ends at once and touches nothing")
def then_the_second_run_leaves(world: PlannerWorld) -> None:
    run = world.scratch["run"]
    assert run.returncode == 0, f"exit {run.returncode}: {run.stderr[-300:]}"
    assert_state_delta(
        world.scratch["before"],
        world.scratch["after"],
        PI,
        {
            "queue.files": predicate(
                "queue.files unchanged but for the heartbeat helper-seen (D315: touched before the lock is looked at)",
                lambda old, new: set(new) - {"helper-seen"} == set(old) - {"helper-seen"},
            ),
            "pi.served_map": unchanged(),
            "pi.refresh_calls": unchanged(),
        },
    )


@then("the result says the rebuild was interrupted")
def then_the_rebuild_was_interrupted(world: PlannerWorld) -> None:
    settled(world, queue=files_after("result.txt", absent=("running.txt",)))
    text = result_text(pi_of(world))
    assert "state=failed" in text and "code=interrupted" in text, (
        f"result: {text!r}; {world.scratch['run'].stderr[-300:]}"
    )


@then("the result says the rebuild ended well")
def then_the_rebuild_ended_well(world: PlannerWorld) -> None:
    settled(world, queue=files_after("result.txt", absent=("running.txt",)))
    text = result_text(pi_of(world))
    assert "state=done" in text, f"result: {text!r}; {world.scratch['run'].stderr[-300:]}"
    assert f"tileset={NEW_MAP}" in text.splitlines(), f"the result does not name the map it made: {text!r}"


@then("the Pi serves the map of 1 November again")
def then_the_old_map_serves_again(world: PlannerWorld) -> None:
    settled(world, queue=files_after("result.txt"), served=unchanged())
    pi = pi_of(world)
    assert served_map(pi) == f"VALHALLA_TILESET={SERVED}", served_map(pi)
    assert pi.valhalla_ups(), f"nothing started the routing engine: {world.scratch['run'].stderr[-300:]}"


@then("the result says the rebuild failed for lack of space, with the free and the needed GB")
def then_the_result_says_disk(world: PlannerWorld) -> None:
    settled(world, queue=files_after("result.txt", absent=("running.txt",)), served=unchanged())
    text = result_text(pi_of(world))
    assert "state=failed" in text and "code=disk" in text, f"result: {text!r}; {world.scratch['run'].stderr[-300:]}"
    assert re.search(r"free_gb=12\b", text) and re.search(r"need_gb=\d+", text), text


# ------------------------------------------------------------------------------------------------- the refresh
def regions_file(world: PlannerWorld, rows: list[list[str]]) -> Path:
    path = world.tmp_path / "regions.tsv"
    path.write_text("\n".join("\t".join(r) for r in rows) + "\n")
    return path


@given("a Pi serving the map of 1 November and a list of regions")
def given_a_pi_and_a_list(world: PlannerWorld) -> None:
    serve(make_pi(world))
    world.scratch["regions"] = regions_file(world, [region_fields("portugal")])


@given("a Pi serving the map of 1 November and a list of regions with two that share a last name")
def given_a_pi_and_two_with_a_shared_name(world: PlannerWorld) -> None:
    serve(make_pi(world))
    world.scratch["regions"] = regions_file(world, [region_fields("georgia"), region_fields("us/georgia")])


@given("a Pi serving the map of 1 November and a list of regions where the border file of Portugal is not found")
def given_a_pi_and_a_missing_border(world: PlannerWorld) -> None:
    pi = make_pi(world)
    serve(pi)
    world.scratch["regions"] = regions_file(world, [region_fields("italy"), region_fields("portugal")])
    pi.rule(
        "docker",
        "valhalla-fetch",
        exit=22,
        stderr="curl: (22) The requested URL returned error: 404\n",  # no name: the refresh must name the region itself
    )


@given(parsers.re(r"a Pi serving the map of 1 November and a list of regions totalling (?P<gb>[\d.]+) GB"))
def given_a_pi_and_a_list_of_a_size(world: PlannerWorld, gb: str) -> None:
    serve(make_pi(world))
    world.scratch["regions"] = regions_file(world, [region_fields("portugal", float(gb))])


@given("a Pi whose seeded map has an integrity check that also covers its regions and borders")
def given_a_seeded_map_with_a_longer_list(world: PlannerWorld) -> None:
    pi = make_pi(world)
    pi.seed_files()
    first = pi.tiles_seed()
    assert first.returncode == 0, f"precondition: the first seed failed: {first.stderr[-300:]}"
    folder = pi.volume / "tilesets" / next(p.name for p in (pi.volume / "tilesets").iterdir())
    (folder / "road-map.json").write_text('{"schema": 1, "regions": []}')
    (folder / "outlines").mkdir()
    (folder / "outlines" / "portugal.poly").write_text("portugal\n")
    sums = (folder / "SHA256SUMS").read_text()
    import hashlib

    extra = [
        f"{hashlib.sha256((folder / n).read_bytes()).hexdigest()}  {n}"
        for n in ("road-map.json", "outlines/portugal.poly")
    ]
    (folder / "SHA256SUMS").write_text(sums.rstrip("\n") + "\n" + "\n".join(extra) + "\n")


@when("the map is seeded again from the same source")
def when_the_map_is_seeded_again(world: PlannerWorld) -> None:
    world.scratch["seed"] = pi_of(world).tiles_seed()


@then("the seed ends saying the map is unchanged")
def then_the_seed_says_unchanged(world: PlannerWorld) -> None:
    result = world.scratch["seed"]
    assert result.returncode == 0 and "unchanged" in result.stderr, f"exit {result.returncode}: {result.stderr[-300:]}"


def refresh(world: PlannerWorld, **env: str) -> subprocess.CompletedProcess[str]:
    pi = pi_of(world)
    world.scratch["before"] = snapshot(pi)
    result = run_in_install(
        pi, "scripts/tiles-refresh.sh", extra={"REGIONS_FILE": str(world.scratch["regions"]), **env}
    )
    world.scratch["refresh"] = result
    world.scratch["after"] = snapshot(pi)
    release_locks(world)
    return result


def refresh_with_borders(world: PlannerWorld, **env: str) -> None:
    pi = pi_of(world)
    # valhalla-fetch leaves the borders it downloaded in the meta folder of the volume (D314); the shim stands for it
    pi.rule(
        "docker",
        "valhalla-fetch",
        write={"road-map-meta/outlines/portugal.poly": "portugal\n"},
        passthrough=True,
        times=1,
    )
    refresh(world, **env)


@when("the rebuild runs on that list")
def when_the_refresh_runs(world: PlannerWorld) -> None:
    refresh_with_borders(world)


@when("the rebuild runs with progress reporting on")
def when_the_refresh_reports(world: PlannerWorld) -> None:
    refresh_with_borders(world, ROAD_MAP_PROGRESS="on")


@when("the rebuild runs with progress reporting off")
def when_the_refresh_is_quiet(world: PlannerWorld) -> None:
    refresh_with_borders(world, ROAD_MAP_PROGRESS="off")


def progress_steps(pi: FakePi) -> list[str]:
    steps = []
    for call in pi.calls("docker"):
        argv = call["argv"]
        if argv[:1] == ["run"] and "-c" in argv and argv[argv.index("-c") + 2 :][:1] == ["progress"]:
            steps.append(argv[argv.index("-c") + 3])
    return steps


@then("each region is downloaded on its own")
def then_each_region_has_its_own_file(world: PlannerWorld) -> None:
    settled(world, queue=ANY, served=ANY, calls=predicate("the rebuild ran", lambda _o, n: len(n) > 0))
    pi = pi_of(world)
    fetches = [" ".join(a) for a in compose_mutations(pi) if "valhalla-fetch" in a]
    assert fetches, f"the refresh never downloaded: {world.scratch['refresh'].stderr[-400:]}"
    wanted = len(Path(world.scratch["regions"]).read_text().splitlines())
    assert len(set(re.findall(r"src/\d+\.osm\.pbf", fetches[0]))) == wanted, fetches[0]


@then("the eight regions of the old list were not downloaded")
def then_the_old_list_was_not_downloaded(world: PlannerWorld) -> None:
    settled(world)
    joined = " ".join(" ".join(a) for a in compose_mutations(pi_of(world)))
    assert "europe/italy-latest.osm.pbf" not in joined and "europe/spain-latest.osm.pbf" not in joined


@then("the rebuild refuses, naming Portugal")
def then_the_refresh_refused_naming_portugal(world: PlannerWorld) -> None:
    settled(world, queue=unchanged(), served=unchanged())
    result = world.scratch["refresh"]
    assert result.returncode != 0 and "portugal" in result.stderr.lower(), result.stderr[-600:]
    assert "border" in result.stderr.lower() or ".poly" in result.stderr.lower(), result.stderr[-600:]


@then("the road service was never stopped and the served map is unchanged")
def then_the_engine_was_never_stopped(world: PlannerWorld) -> None:
    settled(world, queue=unchanged(), served=unchanged())
    pi = pi_of(world)
    assert not any("stop" in a for a in compose_mutations(pi)), compose_mutations(pi)
    assert served_map(pi) == f"VALHALLA_TILESET={SERVED}"


@then("the steps reported were checking, downloading, building and switching, in that order")
def then_the_steps_were_reported(world: PlannerWorld) -> None:
    settled(world)
    steps = progress_steps(pi_of(world))
    assert steps == ["checking", "downloading", "building", "switching"], steps


@then("no step was reported")
def then_no_step_was_reported(world: PlannerWorld) -> None:
    settled(world, queue=unchanged())
    fetches = [" ".join(a) for a in compose_mutations(pi_of(world)) if "valhalla-fetch" in a]
    assert fetches and "src/1.osm.pbf" in fetches[0], (
        "the refresh did not run on the list"
    )  # a silent run is a real run
    steps = progress_steps(pi_of(world))
    assert steps == [], steps


@then("the new map holds the list of its regions, with their names and parents as in the list, and the region borders")
def then_the_map_holds_its_regions_and_borders(world: PlannerWorld) -> None:
    settled(world, queue=unchanged())
    folder = pi_of(world).volume / "tilesets" / REFRESH_DATE
    assert world.scratch["refresh"].returncode == 0, world.scratch["refresh"].stderr[-400:]
    record = folder / "road-map.json"
    assert record.is_file(), f"the new map has no list of regions: {sorted(p.name for p in folder.iterdir())}"
    listed = json.loads(record.read_text())["regions"]
    wanted = [r.split("\t") for r in Path(world.scratch["regions"]).read_text().splitlines()]
    assert [(r["key"], r["name"], r["parent_name"]) for r in listed] == [(w[0], w[1], w[2]) for w in wanted], listed
    assert (folder / "outlines").is_dir() and any((folder / "outlines").iterdir()), "the borders did not travel"


@then("the old map is kept for rollback")
def then_the_old_map_is_kept(world: PlannerWorld) -> None:
    settled(world, queue=unchanged())
    assert sorted(p.name for p in (pi_of(world).volume / "tilesets").iterdir()) == [SERVED, REFRESH_DATE]


@then("the integrity check of the new map covers its tiles, its regions and its borders")
def then_the_sums_name_the_files(world: PlannerWorld) -> None:
    settled(world, queue=unchanged())
    folder = pi_of(world).volume / "tilesets" / REFRESH_DATE
    assert (folder / "SHA256SUMS").is_file(), f"no checked-files list: {world.scratch['refresh'].stderr[-300:]}"
    named = sorted(line.split()[-1] for line in (folder / "SHA256SUMS").read_text().splitlines())
    assert set(TILES_FILES) <= set(named) and "road-map.json" in named, named
    assert any(n.startswith("outlines/") for n in named), named


@then(parsers.re(r"the rebuild (?P<outcome>starts|refuses, saying it needs (?P<need>\d+) GB)"))
def then_the_refresh_outcome(world: PlannerWorld, outcome: str, need: str | None) -> None:
    settled(world)
    result: Any = world.scratch["refresh"]
    if outcome == "starts":
        fetches = [" ".join(a) for a in compose_mutations(pi_of(world)) if "valhalla-fetch" in a]
        assert result.returncode == 0 and fetches and "portugal/portugal-latest.osm.pbf" in fetches[0], result.stderr[
            -400:
        ]
    else:
        assert result.returncode != 0 and f"{need} GB" in result.stderr, result.stderr[-400:]
        assert compose_mutations(pi_of(world)) == [], "the refresh started before refusing"


@then("the rebuild stops saying a deploy is running, which is not a failure")
def then_the_refresh_refused_with_the_lock_code(world: PlannerWorld) -> None:
    settled(world, queue=unchanged(), served=unchanged(), calls=unchanged())
    assert world.scratch["refresh"].returncode == LOCK_REFUSAL, world.scratch["refresh"].returncode


@then("no failure is reported")
def then_the_log_holds_no_failure(world: PlannerWorld) -> None:
    settled(world, queue=unchanged(), served=unchanged(), calls=unchanged())
    failed = [line for line in pi_of(world).tiles_log() if line.get("result") == "failed"]
    assert failed == [] and world.scratch["refresh"].returncode == LOCK_REFUSAL, (
        f"exit {world.scratch['refresh'].returncode}, log {failed}"
    )
