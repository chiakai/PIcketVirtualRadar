from __future__ import annotations

import math
from dataclasses import dataclass


EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class RadarGeometry:
    centre_x: float = 120.0
    centre_y: float = 120.0
    pixel_radius: float = 112.0
    latitude: float = 25.080278
    longitude: float = 121.232222
    radius_km: float = 50.0

    def local_km(self, latitude: float, longitude: float) -> tuple[float, float]:
        delta_lat = math.radians(latitude - self.latitude)
        delta_lon = math.radians(longitude - self.longitude)
        mean_latitude = math.radians((latitude + self.latitude) / 2.0)
        north = EARTH_RADIUS_KM * delta_lat
        east = EARTH_RADIUS_KM * delta_lon * math.cos(mean_latitude)
        return east, north

    def to_screen(self, latitude: float, longitude: float) -> tuple[float, float]:
        east, north = self.local_km(latitude, longitude)
        scale = self.pixel_radius / self.radius_km
        return self.centre_x + east * scale, self.centre_y - north * scale

    def contains(self, latitude: float, longitude: float) -> bool:
        east, north = self.local_km(latitude, longitude)
        return math.hypot(east, north) <= self.radius_km
