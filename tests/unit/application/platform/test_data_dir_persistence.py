"""Whether `DATA_DIR` survives a restart (ADR-011 amendment D121, brief §6 and §7).

Driving port: `DataDirPersistence(data_dir, mount_table).probe()` (the `data_dir` start-up component), with the
`MountTable` port as `FakeMountTable`. Symlink resolution is the composition root's (integration test).
Test Budget: 4 behaviors (longest-prefix verdict, host without a mount table, unknown persistence, the log code of
the verdict) x 2 = 8; 4 property tests used.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.platform.facade import DataDirPersistence, log_reason
from overland_planner.application.ports.probe import ProbeResult
from tests.common.fakes import FakeMountTable
from tests.common.state_delta import assert_state_delta, set_to, unchanged

NOT_PERSISTENT = "Data directory is not persistent - projects would be lost on restart"
# D121: these filesystems live in memory or in a container layer and are gone after a restart.
LOST_ON_RESTART = {"overlay", "tmpfs", "ramfs"}
FILESYSTEMS = sorted(LOST_ON_RESTART | {"ext4", "btrfs", "xfs", "nfs4", "vfat", "zfs", "fuse.sshfs"})
# Names that are string prefixes of each other ("data" / "data2"), so only a component-wise match is right.
NAMES = ["data", "data2", "dat", "srv", "srv data", "planner"]
OUTSIDE_EVERY_MOUNT = "probe-folder"  # never a mount point name: nothing deeper than the target can cover DATA_DIR

mount_points = st.lists(st.sampled_from(NAMES), min_size=1, max_size=3).map(lambda parts: "/" + "/".join(parts))
folders = st.lists(st.sampled_from(NAMES), max_size=3).map(lambda parts: PurePosixPath("/", *parts))


def _verdict(fstypes: set[str]) -> ProbeResult:
    if fstypes & LOST_ON_RESTART:
        return ProbeResult(outcome="degraded-unhealthy", reason=NOT_PERSISTENT)
    return ProbeResult(outcome="ok")


@st.composite
def tables_with_data_dir(
    draw: st.DrawFn,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], PurePosixPath, set[str]]:
    """A mount table with `/`, a target entry, and `DATA_DIR` inside the target but below no deeper entry.

    The target may carry a second, stacked mount: then any non-persistent one of the two decides.
    """
    table = {"/": draw(st.sampled_from(FILESYSTEMS))}
    table.update(draw(st.dictionaries(mount_points, st.sampled_from(FILESYSTEMS), max_size=8)))
    target = draw(st.sampled_from(sorted(table)))
    below = draw(st.lists(st.sampled_from(NAMES), max_size=2))
    inside = [OUTSIDE_EVERY_MOUNT, *below] if draw(st.booleans()) else []
    stacked = draw(st.none() | st.sampled_from(FILESYSTEMS))
    mounts = sorted(table.items()) + ([] if stacked is None else [(target, stacked)])
    entries, reordered = (list(draw(st.permutations(mounts))) for _ in range(2))
    return entries, reordered, PurePosixPath(target, *inside), {table[target]} | ({stacked} - {None})


@given(case=tables_with_data_dir())
def test_the_longest_component_wise_mount_entry_decides_whatever_the_entry_order(
    case: tuple[list[tuple[str, str]], list[tuple[str, str]], PurePosixPath, set[str]],
) -> None:
    entries, reordered, data_dir, deciding_fstypes = case
    table, reordered_table = FakeMountTable(entries), FakeMountTable(reordered)

    before = {"entries": entries, "verdict": None, "verdict_reordered": None}
    after = {
        "entries": table.entries(),
        "verdict": DataDirPersistence(data_dir, table).probe(),
        "verdict_reordered": DataDirPersistence(data_dir, reordered_table).probe(),
    }

    assert_state_delta(
        before,
        after,
        {"entries", "verdict", "verdict_reordered"},
        {
            "entries": unchanged(),
            "verdict": set_to(_verdict(deciding_fstypes)),
            "verdict_reordered": set_to(_verdict(deciding_fstypes)),
        },
        strict=True,
    )


@given(data_dir=folders)
def test_a_host_without_a_mount_table_is_not_applicable_and_healthy(data_dir: PurePosixPath) -> None:
    before = {"verdict": None}
    after = {"verdict": DataDirPersistence(data_dir, FakeMountTable.absent()).probe()}

    assert_state_delta(
        before, after, {"verdict"}, {"verdict": set_to(ProbeResult(outcome="not_applicable"))}, strict=True
    )


uncovered_folders = st.lists(st.sampled_from(NAMES), max_size=2).map(
    lambda p: PurePosixPath("/", OUTSIDE_EVERY_MOUNT, *p)
)
tables_without_root = st.dictionaries(mount_points, st.sampled_from(FILESYSTEMS)).map(
    lambda table: FakeMountTable(sorted(table.items()))
)


@given(data_dir=uncovered_folders, table=st.one_of(st.just(FakeMountTable.unreadable()), tables_without_root))
def test_unknown_persistence_is_degraded_but_healthy(data_dir: PurePosixPath, table: FakeMountTable) -> None:
    """An unreadable table, or one where no entry covers `DATA_DIR` (no `/` entry), cannot vouch for the folder."""
    before = {"verdict": None}
    after = {"verdict": DataDirPersistence(data_dir, table).probe()}

    assert_state_delta(
        before,
        after,
        {"verdict"},
        {"verdict": set_to(ProbeResult(outcome="degraded-healthy", reason="data_dir_persistence_unknown"))},
        strict=True,
    )


@given(other_reason=st.none() | st.text().filter(lambda reason: reason != NOT_PERSISTENT))
def test_the_not_persistent_verdict_is_logged_as_its_code_and_other_reasons_as_they_are(
    other_reason: str | None,
) -> None:
    before = {"not_persistent": NOT_PERSISTENT, "other": other_reason}
    after = {"not_persistent": log_reason(NOT_PERSISTENT), "other": log_reason(other_reason)}

    assert_state_delta(
        before,
        after,
        {"not_persistent", "other"},
        {"not_persistent": set_to("data_dir_not_persistent"), "other": unchanged()},
        strict=True,
    )
