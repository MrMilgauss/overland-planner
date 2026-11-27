"""Step 13-18: `scripts/road-map-helper.sh install | uninstall | status` keeps the helper as one timed job of the deploy
user (D303, D314). The real script runs under /bin/bash with the crontab shim of tests/deploy/shims (never the real
`crontab`): `crontab.txt` of the shim home is the user's list of timed jobs. Assertions are on that list, the files left
in the install folder, the exit code and the messages."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

from tests.deploy.conftest import FakePi

MARKER = "# overland-road-map-runner"
NOTE = "# nightly jobs"
BACKUP = "30 3 * * * /usr/local/bin/backup-home --quiet"
ODD = "  5 4 *  * 1   echo 'two  spaces'\t# tab kept"
OLDER = f"*/5 * * * * cd /old/place && bash scripts/road-map-runner.sh {MARKER}"


def jobs_file(pi: FakePi) -> Path:
    return pi.shim_home / "crontab.txt"


def jobs(pi: FakePi) -> str | None:
    return jobs_file(pi).read_text() if jobs_file(pi).exists() else None


def helper(pi: FakePi, verb: str) -> subprocess.CompletedProcess[str]:
    return pi.run_script("road-map-helper.sh", verb)


def expected_line(pi: FakePi) -> str:
    return f"* * * * * cd '{pi.dir}' && bash scripts/road-map-runner.sh >>road-map-runner.log 2>&1 {MARKER}"


def writes(pi: FakePi) -> list[list[str]]:
    return [c["argv"] for c in pi.calls("crontab") if c["argv"] != ["-l"]]


def saved_copies(pi: FakePi) -> list[str]:
    return [p.read_text() for p in pi.dir.iterdir() if p.is_file() and "crontab" in p.name]


@pytest.mark.parametrize(
    "before",
    [
        None,
        f"{NOTE}\n{BACKUP}\n{ODD}\n",
        f"{NOTE}\n{OLDER}\n{BACKUP}\n",
    ],
    ids=["no crontab", "other jobs", "older helper line"],
)
def test_install_leaves_one_helper_line_after_the_other_jobs_kept_byte_for_byte(pi: FakePi, before: str | None) -> None:
    if before is not None:
        jobs_file(pi).write_text(before)
    others = "".join(line + "\n" for line in (before or "").splitlines() if MARKER not in line)

    result = helper(pi, "install")

    assert result.returncode == 0, result.stderr
    assert jobs(pi) == others + expected_line(pi) + "\n"
    assert all(argv != ["-"] for argv in writes(pi)), "the list is given to crontab as a file, never on a pipe"
    if before:
        assert before in saved_copies(pi), "the earlier list is saved in the install folder"


def test_installing_again_changes_nothing(pi: FakePi) -> None:
    jobs_file(pi).write_text(f"{BACKUP}\n")
    helper(pi, "install")
    once = jobs(pi)

    assert helper(pi, "install").returncode == 0
    assert jobs(pi) == once


@pytest.mark.parametrize("folder", ["my pi", "it's here", "100% sure"])
def test_the_line_runs_from_an_install_folder_whatever_its_name(tmp_path: Path, folder: str) -> None:
    pi = FakePi(tmp_path / folder)

    assert helper(pi, "install").returncode == 0

    (line,) = [x for x in (jobs(pi) or "").splitlines() if MARKER in x]
    command = line.removeprefix("* * * * * ").replace("\\%", "%")
    assert shlex.split(command, comments=True) == [
        "cd",
        str(pi.dir),
        "&&",
        "bash",
        "scripts/road-map-runner.sh",
        ">>road-map-runner.log",
        "2>&1",
    ]


def test_a_list_that_cannot_be_read_is_left_alone(pi: FakePi) -> None:
    jobs_file(pi).write_text(f"{BACKUP}\n")
    pi.rule("crontab", "-l", exit=1, stderr="crontab: cannot read the list of timed jobs: Permission denied\n")

    results = [helper(pi, verb) for verb in ("install", "uninstall")]

    assert all(r.returncode != 0 and "not install" in (r.stdout + r.stderr).lower() for r in results[:1])
    assert results[1].returncode != 0
    assert jobs(pi) == f"{BACKUP}\n"
    assert writes(pi) == []


def test_a_write_that_reads_back_different_is_restored_from_the_saved_copy(pi: FakePi) -> None:
    jobs_file(pi).write_text(f"{NOTE}\n{BACKUP}\n")
    pi.rule("crontab", ".road-map-crontab.new", passthrough=True, stored_text="garbled\n", times=1)

    result = helper(pi, "install")

    assert result.returncode != 0
    assert "warning" in (result.stdout + result.stderr).lower()
    assert jobs(pi) == f"{NOTE}\n{BACKUP}\n"


def test_uninstall_removes_only_the_helper_line(pi: FakePi) -> None:
    jobs_file(pi).write_text(f"{NOTE}\n{BACKUP}\n{expected_line(pi)}\n{ODD}\n")

    result = helper(pi, "uninstall")

    assert result.returncode == 0, result.stderr
    assert jobs(pi) == f"{NOTE}\n{BACKUP}\n{ODD}\n"


@pytest.mark.parametrize("before", [None, f"{BACKUP}\n"], ids=["no crontab", "no helper line"])
def test_uninstall_with_nothing_to_remove_writes_nothing_and_succeeds(pi: FakePi, before: str | None) -> None:
    if before is not None:
        jobs_file(pi).write_text(before)

    assert helper(pi, "uninstall").returncode == 0
    assert jobs(pi) == before
    assert writes(pi) == []


@pytest.mark.parametrize("before", [None, f"{BACKUP}\n"], ids=["no crontab", "no helper line"])
def test_status_says_not_installed_and_changes_nothing(pi: FakePi, before: str | None) -> None:
    if before is not None:
        jobs_file(pi).write_text(before)

    result = helper(pi, "status")

    assert result.returncode == 1
    assert "not installed" in result.stdout + result.stderr
    assert jobs(pi) == before
    assert writes(pi) == []


def test_status_says_installed_and_changes_nothing(pi: FakePi) -> None:
    jobs_file(pi).write_text(f"{BACKUP}\n{expected_line(pi)}\n")

    result = helper(pi, "status")

    assert result.returncode == 0
    assert "not installed" not in result.stdout + result.stderr
    assert "installed" in result.stdout + result.stderr
    assert writes(pi) == []


def test_only_the_five_newest_saved_lists_are_kept(pi: FakePi) -> None:
    jobs_file(pi).write_text(f"{BACKUP}\n")
    for day in range(1, 9):
        old = pi.dir / f"crontab.before-road-map-helper.2026110{day}T030000Z.1"
        old.write_text(f"old {day}\n")
    other = pi.dir / "crontab.txt.mine"
    other.write_text("not ours\n")

    assert helper(pi, "install").returncode == 0

    kept = sorted(p.name for p in pi.dir.iterdir() if p.name.startswith("crontab.before-road-map-helper."))
    assert len(kept) == 5
    assert all(f"2026110{day}T" not in " ".join(kept) for day in (1, 2, 3, 4))  # the four oldest of the eight are gone
    assert any(f"2026110{day}T" in " ".join(kept) for day in (6, 7, 8)) and other.exists()
    assert BACKUP + "\n" in saved_copies(pi), "the list this run saved is among the newest"
