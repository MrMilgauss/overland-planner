"""How long a road-map rebuild takes (D305): pause = round(6 x GB), total = round(8.2 x GB + 2.5) minutes."""

from __future__ import annotations

import math
from dataclasses import dataclass

BYTES_PER_GB = 1_000_000_000


@dataclass(frozen=True)
class Estimate:
    total_minutes: int
    pause_minutes: int


def estimate(total_bytes: int) -> Estimate:
    gb = total_bytes / BYTES_PER_GB
    return Estimate(
        total_minutes=math.floor(8.2 * gb + 2.5 + 0.5),
        pause_minutes=math.floor(6 * gb + 0.5),
    )
