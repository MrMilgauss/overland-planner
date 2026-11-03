"""Test data folders under the workspace (ADR-011 D121, D182, review H-02), never under the OS temp folder.

On many Linux hosts /tmp is tmpfs, which the persistence probe rightly reports as not persistent. Root: env
PLANNER_TEST_WORKSPACE, else <repo>/.data (git-ignored; in CI the checkout under $GITHUB_WORKSPACE).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def workspace_data_dir(suite: str) -> Iterator[Path]:
    """A fresh, empty `<root>/<suite>/<12 hex>/data`, removed with its parent afterwards.

    Folders a test made read-only are made writable again first, so the removal never leaves them behind.
    """
    root = Path(os.environ.get("PLANNER_TEST_WORKSPACE", REPO_ROOT / ".data")) / suite
    folder = root / uuid.uuid4().hex[:12] / "data"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        _make_writable(folder)
        shutil.rmtree(folder.parent, ignore_errors=True)


def _make_writable(folder: Path) -> None:
    if not folder.is_dir():
        return
    folder.chmod(0o755)  # before listing it: a read-only folder hides its children
    for path in folder.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
