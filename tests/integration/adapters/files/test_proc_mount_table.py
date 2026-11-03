"""`ProcMountTable` over real mountinfo files (ADR-011 amendment D121, brief §6).

Integration level: the gold mountinfo samples (D121) and this host's own table are single examples; the octal
escape decoding of the mount point is a property, because any path must survive the kernel's encoding.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.files.proc_mount_table import MOUNTINFO, ProcMountTable
from overland_planner.application.ports.host import MountTableUnreadableError
from overland_planner.application.ports.probe import ProbeResult

UNKNOWN = ProbeResult(outcome="degraded-healthy", reason="data_dir_persistence_unknown")

# A container without a volume on /data, with a tmpfs and a bind mount (one carrying a space), as Docker writes it.
CONTAINER_MOUNTINFO = """\
1089 1001 0:58 / / rw,relatime master:312 - overlay overlay rw,lowerdir=/var/lib/docker/l1,upperdir=/u,workdir=/w
1090 1089 0:61 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw
1091 1089 0:62 / /dev rw,nosuid - tmpfs tmpfs rw,size=65536k,mode=755
1092 1089 259:2 /var/lib/docker/volumes/overland-data/_data /data rw,relatime - ext4 /dev/nvme0n1p2 rw
1093 1089 0:63 / /run/planner\\040scratch rw,nosuid shared:4 master:1 - tmpfs tmpfs rw
"""


def _table(tmp_folder: Path, text: str) -> ProcMountTable:
    file = tmp_folder / "mountinfo"
    file.write_text(text)
    return ProcMountTable(file, linux=True)


def test_a_container_mount_table_lists_every_mount_point_with_its_filesystem(tmp_path: Path) -> None:
    table = _table(tmp_path, CONTAINER_MOUNTINFO)

    assert table.entries() == [
        ("/", "overlay"),
        ("/proc", "proc"),
        ("/dev", "tmpfs"),
        ("/data", "ext4"),
        ("/run/planner scratch", "tmpfs"),
    ]
    assert table.probe() == ProbeResult(outcome="ok")


@pytest.mark.parametrize(
    "text",
    ["36 35 98:0 /mnt1 /mnt2 rw,noatime master:1 ext3 /dev/root rw\n", "not a mount line\n"],
    ids=["no separator", "garbage"],
)
def test_an_unparsable_mount_table_on_linux_is_unknown(tmp_path: Path, text: str) -> None:
    table = _table(tmp_path, text)

    with pytest.raises(MountTableUnreadableError):
        table.entries()
    assert table.probe() == UNKNOWN


def test_a_mount_table_without_root_or_a_missing_one_on_linux_is_unknown(tmp_path: Path) -> None:
    without_root = _table(tmp_path, "1092 1089 259:2 / /data rw - ext4 /dev/sda1 rw\n")
    missing = ProcMountTable(tmp_path / "absent", linux=True)

    assert (without_root.probe(), missing.probe()) == (UNKNOWN, UNKNOWN)


def test_this_host_mount_table_has_root_or_is_not_applicable() -> None:
    table = ProcMountTable()

    if MOUNTINFO.exists():
        assert ("/" in {mount for mount, _ in table.entries() or []}, table.probe()) == (True, ProbeResult("ok"))
    else:
        assert (table.entries(), table.probe()) == (None, ProbeResult(outcome="not_applicable"))


def _kernel_escape(path: str) -> str:
    """How the kernel writes a mount point into mountinfo (fs/proc_namespace.c: mangle " \\t\\n\\\\")."""
    return "".join(f"\\{ord(c):03o}" if c in " \t\n\\" else c for c in path)


paths = st.lists(
    st.text(st.characters(blacklist_categories=("Cs",), blacklist_characters="/\x00"), min_size=1, max_size=8),
    min_size=1,
    max_size=4,
).map(lambda parts: "/" + "/".join(parts))


@settings(max_examples=50)
@given(path=paths)
def test_any_mount_point_survives_the_kernel_escaping(path: str) -> None:
    with tempfile.TemporaryDirectory() as folder:
        table = _table(
            Path(folder), f"1 0 0:1 / / rw - ext4 /dev/sda1 rw\n2 1 0:2 / {_kernel_escape(path)} rw - tmpfs t rw\n"
        )

        assert table.entries() == [("/", "ext4"), (path, "tmpfs")]
