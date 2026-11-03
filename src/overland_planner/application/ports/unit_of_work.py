"""UnitOfWork port (brief §6, ADR-006, ADR-018): one transaction per use case under the single writer lock.

A use case opens one unit of work, does its reads and writes through the repositories bound to it, and calls
`commit()`; leaving the block without a commit rolls every change back. Only one unit of work writes at a time.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self


class UnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None:
        """Make every change of this unit of work durable."""
        ...
