"""File store port (brief §4 and §6): the planner's own files under `DATA_DIR` (exports, imports, scratch files).

Its start-up probe proves a file can be written, synced, renamed and read back under `DATA_DIR/tmp`; any failure is
fatal (component `file_store`). Production adapter: `adapters/files/local_file_store.py`.
"""

from __future__ import annotations

from typing import Protocol

from overland_planner.application.ports.probe import Probeable


class FileStore(Probeable, Protocol):
    """The planner's file storage under `DATA_DIR`; file operations arrive with the features that need them."""
