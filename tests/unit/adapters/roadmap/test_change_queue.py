"""ChangeQueueDir against real folders (D303, D310, D315): what the helper finds, all or nothing, one winner of the
race for `request.txt`, and a probe that says why the folder cannot keep changes. Real I/O under tmp_path only."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from overland_planner.adapters.roadmap.change_queue import ChangeQueueDir
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.road_map_changes import (
    ChangeRequest,
    ChangesUnavailableError,
    RequestedRegion,
)

NOW = datetime(2026, 11, 28, 21, 0, tzinfo=UTC)
START = datetime(2026, 11, 29, 2, 0, tzinfo=UTC)
ITALY = RequestedRegion("italy", "Italy", "Europe", "https://dl.test/italy.pbf", "https://dl.test/italy.poly", 2)
UTAH = RequestedRegion(
    "us/utah", "Utah", "United States of America", "https://dl.test/u.pbf", "https://dl.test/u.poly", 7
)
EUROPE = RequestedRegion("europe", "Europe", None, "https://dl.test/europe.pbf", "https://dl.test/europe.poly", 9)
UNAVAILABLE = ProbeResult(outcome="degraded-healthy", reason="road_map_changes_unavailable")


def request(*regions: RequestedRegion, start_at: datetime | None = START) -> ChangeRequest:
    return ChangeRequest(requested_at=NOW, start_at=start_at, regions=regions)


def names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def test_a_request_is_kept_as_the_lines_the_helper_reads_and_nothing_else_is_left(tmp_path: Path) -> None:
    ChangeQueueDir(tmp_path).queue(request(ITALY, UTAH, EUROPE), added=["Utah", "Europe"], removed=["Spain"])
    assert names(tmp_path) == ["request.txt"]
    assert (tmp_path / "request.txt").read_text(encoding="utf-8").splitlines() == [
        "schema=1",
        f"requested_at={int(NOW.timestamp())}",
        f"start_at={int(START.timestamp())}",
        f"region=italy\tItaly\tEurope\t{ITALY.pbf_url}\t{ITALY.poly_url}\t2",
        f"region=us/utah\tUtah\tUnited States of America\t{UTAH.pbf_url}\t{UTAH.poly_url}\t7",
        f"region=europe\tEurope\t\t{EUROPE.pbf_url}\t{EUROPE.poly_url}\t9",
        "added=Utah, Europe",
        "removed=Spain",
    ]


def test_a_request_without_a_start_has_no_start_line_and_reads_back_as_written(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    sent = request(ITALY, EUROPE, start_at=None)
    queue.queue(sent, added=[], removed=[])
    assert "start_at" not in (tmp_path / "request.txt").read_text()
    assert queue.pending() == sent
    queue.queue(request(ITALY, UTAH), added=["Utah"], removed=[])
    assert queue.pending() == request(ITALY, UTAH)


def test_nothing_is_pending_without_a_request_or_with_one_that_is_not_a_request(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    assert queue.pending() is None
    (tmp_path / "request.txt").write_text("schema=2\nrequested_at=zzz\n")
    assert queue.pending() is None


def test_a_reader_never_sees_a_half_written_request(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    long_address = "https://dl.test/" + "x" * 3000
    many = request(*[RequestedRegion(f"r{i}", f"Region {i}", "Europe", long_address, "p", i) for i in range(40)])
    seen: set[str] = set()
    done = threading.Event()

    def reader() -> None:
        while not done.is_set():
            try:
                seen.add((tmp_path / "request.txt").read_text())
            except FileNotFoundError:
                continue

    watcher = threading.Thread(target=reader)
    watcher.start()
    try:
        for _ in range(60):
            queue.queue(many, added=["Region 1"], removed=[])
            queue.cancel()
    finally:
        done.set()
        watcher.join()
    assert len(seen) == 1
    assert next(iter(seen)).endswith("removed=\n")


def test_a_cancelled_request_can_no_longer_be_taken_and_a_second_cancel_finds_nothing(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    assert queue.cancel() is False
    queue.queue(request(ITALY), added=[], removed=[])
    kept = (tmp_path / "request.txt").read_text()
    assert queue.cancel() is True
    assert names(tmp_path) == ["cancelled.txt"]
    assert (tmp_path / "cancelled.txt").read_text() == kept
    assert queue.pending() is None
    assert queue.cancel() is False


def test_a_request_the_helper_has_taken_cannot_be_cancelled(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    queue.queue(request(ITALY), added=[], removed=[])
    (tmp_path / "request.txt").rename(tmp_path / "running.txt")  # the helper's take
    assert queue.cancel() is False
    assert names(tmp_path) == ["running.txt"]


def test_of_two_cancels_at_once_one_wins(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    for _ in range(40):
        queue.queue(request(ITALY), added=[], removed=[])
        outcomes: list[bool] = []
        gate = threading.Barrier(2)

        def race(outcomes: list[bool] = outcomes, gate: threading.Barrier = gate) -> None:
            gate.wait()
            outcomes.append(queue.cancel())

        threads = [threading.Thread(target=race) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == [False, True]


@pytest.fixture
def folders(tmp_path: Path) -> Iterator[dict[str, Path]]:
    plain_file = tmp_path / "a-file"
    plain_file.write_text("not a folder\n")
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(0o500)
    yield {
        "a missing mount": tmp_path / "no-such-mount" / "changes",
        "a plain file in its place": plain_file,
        "a read-only folder": read_only,
        "a folder of root": Path("/"),
    }
    read_only.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")
@pytest.mark.parametrize(
    "fault", ["a missing mount", "a plain file in its place", "a read-only folder", "a folder of root"]
)
def test_a_folder_that_cannot_be_written_keeps_nothing_and_says_why(folders: dict[str, Path], fault: str) -> None:
    folder = folders[fault]
    queue = ChangeQueueDir(folder)
    before = names(folder) if folder.is_dir() else None
    assert queue.available() is False
    assert queue.probe() == UNAVAILABLE
    with pytest.raises(ChangesUnavailableError):
        queue.queue(request(ITALY), added=[], removed=[])
    assert (names(folder) if folder.is_dir() else None) == before


def test_a_folder_that_can_be_written_is_available_and_the_probe_leaves_nothing(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    assert queue.available() is True
    assert queue.probe() == ProbeResult(outcome="ok")
    assert names(tmp_path) == []


def test_a_new_request_moves_the_last_result_aside_and_forgets_a_cancel(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    (tmp_path / "result.txt").write_text("status=failed\n")
    (tmp_path / "previous-result.txt").write_text("older\n")
    (tmp_path / "cancelled.txt").write_text("old cancel\n")
    queue.queue(request(ITALY), added=[], removed=[])
    assert names(tmp_path) == ["previous-result.txt", "request.txt"]
    assert (tmp_path / "previous-result.txt").read_text() == "status=failed\n"


def test_the_folder_says_whether_a_request_waits_or_the_helper_runs_one(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    assert (queue.waiting(), queue.running()) == (False, False)
    queue.queue(request(ITALY), added=[], removed=[])
    assert (queue.waiting(), queue.running()) == (True, False)
    (tmp_path / "request.txt").rename(tmp_path / "running.txt")
    assert (queue.waiting(), queue.running()) == (False, True)


# ------------------------------------------------------------------ what the helper writes: heartbeat and progress
def test_the_helper_mark_gives_its_time_and_no_mark_gives_none(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    assert queue.helper_seen_at() is None
    (tmp_path / "helper-seen").touch()
    os.utime(tmp_path / "helper-seen", (NOW.timestamp(), NOW.timestamp()))
    assert queue.helper_seen_at() == NOW


def test_a_rebuild_taken_by_the_helper_is_read_with_its_regions_and_step(tmp_path: Path) -> None:
    queue = ChangeQueueDir(tmp_path)
    queue.queue(request(ITALY, UTAH), added=["Utah"], removed=[])
    assert queue.running_request() is None
    (tmp_path / "request.txt").rename(tmp_path / "running.txt")
    assert queue.running_request() == request(ITALY, UTAH) and queue.pending() is None
    assert queue.progress() is None
    (tmp_path / "progress.txt").write_text(
        f"step=building\nstep_at={int(NOW.timestamp())}\nserving=20261101\nnew=20261128\n"
    )
    progress = queue.progress()
    assert progress is not None and (progress.step, progress.step_at) == ("building", NOW)


def hostile(folder: Path, kind: str) -> None:
    target = folder / "progress.txt"
    good = f"step=building\nstep_at={int(NOW.timestamp())}\n"
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        (folder / "elsewhere.txt").write_text(good)
        target.symlink_to(folder / "elsewhere.txt")
    elif kind == "too large":
        target.write_text(good + "serving=" + "x" * 5000 + "\n")
    elif kind == "unknown key":
        target.write_text(good + "colour=red\n")
    elif kind == "repeated key":
        target.write_text(good + "step=checking\n")
    elif kind == "unknown step":
        target.write_text(f"step=frying\nstep_at={int(NOW.timestamp())}\n")
    elif kind == "not a number":
        target.write_text("step=building\nstep_at=soon\n")
    else:
        target.write_bytes(b"step=\xff\xfe\n")


@pytest.mark.parametrize(
    "kind",
    ["directory", "symlink", "too large", "unknown key", "repeated key", "unknown step", "not a number", "not text"],
)
def test_a_note_that_is_not_plain_and_strict_says_nothing_and_never_fails(tmp_path: Path, kind: str) -> None:
    hostile(tmp_path, kind)
    assert ChangeQueueDir(tmp_path).progress() is None


def test_a_mark_that_is_not_a_plain_file_says_nothing(tmp_path: Path) -> None:
    (tmp_path / "helper-seen").mkdir()
    assert ChangeQueueDir(tmp_path).helper_seen_at() is None


# ------------------------------------------------------------------------------ the helper's result (D303, D304)
FINISHED = int(datetime(2026, 11, 29, 2, 56, tzinfo=UTC).timestamp())


def write_result(folder: Path, *lines: str, with_request: bool = True) -> None:
    queue = ChangeQueueDir(folder)
    queue.queue(request(ITALY, UTAH), added=["Utah"], removed=["Spain"])
    text = (folder / "request.txt").read_text() if with_request else ""
    (folder / "request.txt").unlink()
    (folder / "result.txt").write_text(text + "\n".join(lines) + "\n")


def test_no_result_says_nothing(tmp_path: Path) -> None:
    assert ChangeQueueDir(tmp_path).result() is None


def test_a_failed_result_gives_its_code_numbers_and_the_request_it_kept(tmp_path: Path) -> None:
    write_result(tmp_path, f"finished_at={FINISHED}", "state=failed", "code=disk", "free_gb=18", "need_gb=25")
    found = ChangeQueueDir(tmp_path).result()
    assert found is not None
    assert (found.state, found.code, found.free_gb, found.need_gb, found.have_gb, found.tileset) == (
        "failed",
        "disk",
        18,
        25,
        None,
        None,
    )
    assert found.finished_at == datetime.fromtimestamp(FINISHED, UTC)
    assert found.request == request(ITALY, UTAH)
    assert (found.added, found.removed) == (("Utah",), ("Spain",))


def test_a_done_result_gives_the_tileset(tmp_path: Path) -> None:
    write_result(tmp_path, f"finished_at={FINISHED}", "state=done", "tileset=20261129")
    found = ChangeQueueDir(tmp_path).result()
    assert found is not None and (found.state, found.tileset, found.code) == ("done", "20261129", None)


def test_a_result_without_the_request_lines_still_says_how_it_ended(tmp_path: Path) -> None:
    write_result(tmp_path, f"finished_at={FINISHED}", "state=failed", "code=build", with_request=False)
    found = ChangeQueueDir(tmp_path).result()
    assert found is not None and (found.code, found.request, found.added) == ("build", None, ())


@pytest.mark.parametrize(
    "lines",
    [
        ["state=done", "tileset=20261129"],  # no finished_at
        [f"finished_at={FINISHED}", "state=maybe"],
        [f"finished_at={FINISHED}", "state=failed", "code=disk", "free_gb=lots"],
        [f"finished_at={FINISHED}", "state=failed", "code=Disk Full!"],
        [f"finished_at={FINISHED}", "state=failed", "message=free text from the helper"],
        [f"finished_at={FINISHED}", "state=failed", "state=done"],
        [f"finished_at={FINISHED}", "state=done", "tileset=../etc"],
        [f"finished_at={FINISHED}", "state=failed", "free text without a key"],
    ],
)
def test_a_result_that_is_not_strictly_the_known_keys_says_nothing(tmp_path: Path, lines: list[str]) -> None:
    write_result(tmp_path, *lines)
    assert ChangeQueueDir(tmp_path).result() is None


def test_a_result_over_four_kilobytes_or_not_a_plain_file_says_nothing(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text(f"finished_at={FINISHED}\nstate=failed\ncode=disk\n" + "x" * 5000)
    assert ChangeQueueDir(tmp_path).result() is None
    (tmp_path / "result.txt").unlink()
    (tmp_path / "elsewhere.txt").write_text(f"finished_at={FINISHED}\nstate=failed\ncode=disk\n")
    (tmp_path / "result.txt").symlink_to(tmp_path / "elsewhere.txt")
    assert ChangeQueueDir(tmp_path).result() is None
