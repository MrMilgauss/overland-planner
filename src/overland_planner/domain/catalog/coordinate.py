"""A point on the Earth's surface in WGS84 degrees, shared by track points and POIs (03-08). Pure domain.

Range rule: latitude -90..90 and longitude -180..180, both inclusive; anything else (including NaN) is refused.
Distances use the haversine great-circle formula on a sphere of the IUGG mean Earth radius R1 = 6 371 008.8 m.
The spherical model differs from the WGS84 ellipsoid by at most about 0.5 %, well inside the 1 % import check
(US-02a S1), so the radius choice is not critical; the mean radius minimises the average error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MEAN_EARTH_RADIUS_M = 6_371_008.8


class CoordinateOutOfRangeError(ValueError):
    """A latitude outside -90..90 or a longitude outside -180..180 degrees."""

    def __init__(self, latitude: float, longitude: float) -> None:
        super().__init__(f"Coordinate out of range: latitude {latitude}, longitude {longitude}")


@dataclass(frozen=True)
class Coordinate:
    """Latitude and longitude in degrees, range-checked on creation."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not (-90.0 <= self.latitude <= 90.0 and -180.0 <= self.longitude <= 180.0):
            raise CoordinateOutOfRangeError(self.latitude, self.longitude)

    def great_circle_distance_m(self, other: Coordinate) -> float:
        """Haversine distance in metres along the sphere's surface."""
        lat1, lat2 = math.radians(self.latitude), math.radians(other.latitude)
        half_dlat = (lat2 - lat1) / 2
        half_dlon = math.radians(other.longitude - self.longitude) / 2
        h = math.sin(half_dlat) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(half_dlon) ** 2
        return 2 * MEAN_EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))
