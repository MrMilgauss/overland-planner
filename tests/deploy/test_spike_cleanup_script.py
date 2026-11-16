"""Step 08-03: `make spike-cleanup` runs scripts/spike-cleanup.sh on the Pi (D92, D178, D237), offline.

A fake Pi is seeded through the real tiles-seed.sh first (the volume is a host directory behind the docker shim); the
cleanup guards are then driven through `check` (removes nothing) and `delete`. The typed confirmation belongs to the
Makefile and is tested in test_makefile_targets.py.
"""

from __future__ import annotations

import os

import pytest

from tests.deploy.conftest import TILES_FILES, TILESET, FakePi


@pytest.fixture
def seeded(pi: FakePi) -> FakePi:
    pi.seed_files()
    (pi.spike / "custom_files" / "extra.bin").write_bytes(b"not part of the checksums\n")
    (pi.spike / "tiles").mkdir()
    (pi.spike / "tiles" / "0.gph").write_bytes(b"x")
    seeded_run = pi.tiles_seed()
    assert seeded_run.returncode == 0, seeded_run.stderr
    return pi


def removals(pi: FakePi) -> list[list[str]]:
    return pi.helper_runs("remove-spike")


def test_check_passes_and_removes_nothing(seeded: FakePi) -> None:
    result = seeded.run_script("spike-cleanup.sh", "check")

    assert result.returncode == 0, result.stderr
    assert "every guard holds" in result.stderr
    assert (seeded.spike / "custom_files" / "valhalla_tiles.tar").exists() and not removals(seeded)


def test_delete_removes_exactly_the_spike_directory_through_the_helper_container(seeded: FakePi) -> None:
    keep = seeded.root / "valhalla-spike-other"
    keep.mkdir()
    result = seeded.run_script("spike-cleanup.sh", "delete")

    assert result.returncode == 0, result.stderr
    assert not seeded.spike.exists() and keep.exists()
    assert (seeded.volume / "tilesets" / TILESET / "valhalla.json").exists()  # the seeded copy stays
    (run,) = removals(seeded)
    assert run[:4] == ["run", "--rm", "--network", "none"] and run[-1] == "remove-spike"
    assert f"{seeded.spike}:/target" in run and "sudo" not in run
    assert seeded.tiles_log()[-1]["action"] == "spike-cleanup" and seeded.tiles_log()[-1]["result"] == "ok"


@pytest.mark.parametrize("tamper", ["original", "copy", "stored-sums"])
def test_a_checksum_mismatch_refuses_and_removes_nothing(seeded: FakePi, tamper: str) -> None:
    target = {
        "original": seeded.spike / "custom_files" / TILES_FILES[0],
        "copy": seeded.volume / "tilesets" / TILESET / TILES_FILES[0],
        "stored-sums": seeded.volume / "tilesets" / TILESET / "SHA256SUMS",
    }[tamper]
    target.write_text("tampered\n")

    result = seeded.run_script("spike-cleanup.sh", "delete")

    assert result.returncode == 1
    assert "refused" in result.stderr and "differ" in result.stderr
    assert (seeded.spike / "tiles" / "0.gph").exists() and not removals(seeded)
    assert seeded.tiles_log()[-1]["result"] == "refused"


def test_a_symlinked_target_is_refused_and_the_link_target_is_never_touched(seeded: FakePi) -> None:
    elsewhere = seeded.root / "precious"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("keep\n")
    moved = seeded.root / "moved-spike"
    seeded.spike.rename(moved)
    os.symlink(elsewhere, seeded.spike)

    result = seeded.run_script("spike-cleanup.sh", "delete")

    assert result.returncode == 1 and "not a real directory" in result.stderr
    assert (elsewhere / "keep.txt").exists() and (moved / "tiles").exists() and not removals(seeded)


@pytest.mark.parametrize(
    ("rule", "problem"),
    [
        ({"exit": 1}, "does not answer /status"),
        ({"stdout": '{"version":"3.9.1","tileset_last_modified":1700000000}'}, "tiles.log recorded '1793560782'"),
    ],
)
def test_valhalla_not_healthy_on_the_seeded_tileset_refuses(
    seeded: FakePi, rule: dict[str, object], problem: str
) -> None:
    seeded.rule("docker", "exec", **rule)

    result = seeded.run_script("spike-cleanup.sh", "delete")

    assert result.returncode == 1 and problem in result.stderr
    assert (seeded.spike / "tiles" / "0.gph").exists() and not removals(seeded)


def test_without_routing_env_it_refuses(seeded: FakePi) -> None:
    (seeded.dir / "routing.env").unlink()

    result = seeded.run_script("spike-cleanup.sh", "delete")

    assert result.returncode == 1 and "routing.env names no tileset" in result.stderr
    assert seeded.spike.exists() and not removals(seeded)


@pytest.mark.parametrize("args", [("everything",), ("--target", "/"), ("/etc",)])
def test_no_argument_can_change_the_target_the_only_modes_are_check_and_delete(
    seeded: FakePi, args: tuple[str, ...]
) -> None:
    before = len(seeded.calls("docker"))

    result = seeded.run_script("spike-cleanup.sh", *args)

    assert result.returncode == 2 and "usage" in result.stderr
    assert len(seeded.calls("docker")) == before and seeded.spike.exists()


@pytest.mark.parametrize("rule", [{"exit": 1}, {"exit": 0}], ids=["helper fails", "helper leaves files so rmdir fails"])
def test_a_removal_that_fails_part_way_does_not_claim_that_nothing_was_removed(
    seeded: FakePi, rule: dict[str, int]
) -> None:
    seeded.rule("docker", "remove-spike", **rule)

    result = seeded.run_script("spike-cleanup.sh", "delete")

    assert result.returncode == 1
    assert "removal failed part-way; ~/valhalla-spike may be partly removed" in result.stderr
    assert "nothing removed" not in result.stderr
    assert (seeded.tiles_log()[-1]["result"], "partly removed" in seeded.tiles_log()[-1]["reason"]) == ("failed", True)
