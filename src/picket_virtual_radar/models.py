from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AircraftView:
    icao24: str
    callsign: str
    latitude: float
    longitude: float
    heading: float
    altitude_m: float | None = None
    velocity_mps: float | None = None
    vertical_rate_mps: float | None = None
    on_ground: bool = False
    last_contact_epoch: float | None = None
    data_age_seconds: float = 0.0
    predicted: bool = False
