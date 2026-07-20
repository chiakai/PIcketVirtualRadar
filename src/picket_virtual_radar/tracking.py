from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from typing import Iterable

from .config import TrackingConfig
from .geometry import EARTH_RADIUS_KM
from .models import AircraftView


@dataclass
class _Track:
    state: AircraftView
    start_latitude: float
    start_longitude: float
    target_latitude: float
    target_longitude: float
    updated_at: float
    last_seen_at: float
    initial_age_seconds: float


class AircraftTracker:
    """Maintains ICAO24 tracks and produces smooth, age-labelled views."""

    def __init__(self, config: TrackingConfig, clock=time.monotonic, wall_clock=time.time) -> None:
        self.config = config
        self.clock = clock
        self.wall_clock = wall_clock
        self._tracks: dict[str, _Track] = {}
        self.show_on_ground = config.show_on_ground

    @property
    def count(self) -> int:
        return len(self._tracks)

    def set_show_on_ground(self, enabled: bool) -> None:
        self.show_on_ground = enabled
        if not enabled:
            self._tracks = {
                key: track for key, track in self._tracks.items() if not track.state.on_ground
            }

    def ingest(self, aircraft: Iterable[AircraftView], now: float | None = None) -> None:
        timestamp = self.clock() if now is None else now
        wall_timestamp = self.wall_clock()
        for incoming in aircraft:
            if incoming.on_ground and not self.show_on_ground:
                continue
            key = incoming.icao24.strip().lower()
            if not key:
                continue
            initial_age = 0.0
            if incoming.last_contact_epoch is not None:
                initial_age = max(0.0, min(86400.0, wall_timestamp - incoming.last_contact_epoch))
            existing = self._tracks.get(key)
            if existing is None:
                self._tracks[key] = _Track(
                    state=replace(incoming, icao24=key),
                    start_latitude=incoming.latitude,
                    start_longitude=incoming.longitude,
                    target_latitude=incoming.latitude,
                    target_longitude=incoming.longitude,
                    updated_at=timestamp,
                    last_seen_at=timestamp,
                    initial_age_seconds=initial_age,
                )
                continue
            current_latitude, current_longitude, _ = self._position(existing, timestamp)
            existing.state = replace(incoming, icao24=key)
            existing.start_latitude = current_latitude
            existing.start_longitude = current_longitude
            existing.target_latitude = incoming.latitude
            existing.target_longitude = incoming.longitude
            existing.updated_at = timestamp
            existing.last_seen_at = timestamp
            existing.initial_age_seconds = initial_age
        self.prune(timestamp)

    def prune(self, now: float | None = None) -> None:
        timestamp = self.clock() if now is None else now
        expired = [key for key, track in self._tracks.items() if timestamp - track.last_seen_at > self.config.stale_after_seconds]
        for key in expired:
            del self._tracks[key]

    def _position(self, track: _Track, now: float) -> tuple[float, float, bool]:
        elapsed = max(0.0, now - track.updated_at)
        interpolation = self.config.interpolation_seconds
        if interpolation > 0 and elapsed < interpolation:
            fraction = elapsed / interpolation
            return (
                track.start_latitude + (track.target_latitude - track.start_latitude) * fraction,
                track.start_longitude + (track.target_longitude - track.start_longitude) * fraction,
                False,
            )

        latitude = track.target_latitude
        longitude = track.target_longitude
        prediction_elapsed = min(max(0.0, elapsed - interpolation), self.config.prediction_seconds)
        state = track.state
        if prediction_elapsed <= 0 or state.on_ground or state.velocity_mps is None or state.velocity_mps <= 0:
            return latitude, longitude, False

        distance_km = state.velocity_mps * prediction_elapsed / 1000.0
        heading = math.radians(state.heading)
        north_km = distance_km * math.cos(heading)
        east_km = distance_km * math.sin(heading)
        latitude += math.degrees(north_km / EARTH_RADIUS_KM)
        cosine = max(0.01, abs(math.cos(math.radians(latitude))))
        longitude += math.degrees(east_km / (EARTH_RADIUS_KM * cosine))
        return latitude, longitude, True

    def views(self, now: float | None = None) -> tuple[AircraftView, ...]:
        timestamp = self.clock() if now is None else now
        self.prune(timestamp)
        result = []
        for key in sorted(self._tracks):
            track = self._tracks[key]
            latitude, longitude, predicted = self._position(track, timestamp)
            result.append(
                replace(
                    track.state,
                    latitude=latitude,
                    longitude=longitude,
                    data_age_seconds=track.initial_age_seconds + max(0.0, timestamp - track.updated_at),
                    predicted=predicted,
                )
            )
        return tuple(result)
