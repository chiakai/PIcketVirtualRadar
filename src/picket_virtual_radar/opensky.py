from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol

from .config import OpenSkyConfig
from .geometry import EARTH_RADIUS_KM, RadarGeometry
from .models import AircraftView


LOG = logging.getLogger(__name__)
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class HttpTransport(Protocol):
    def request(self, url: str, *, method: str = "GET", headers: Mapping[str, str] | None = None, data: bytes | None = None, timeout: float = 8.0) -> HttpResponse: ...


class UrllibTransport:
    def request(self, url: str, *, method: str = "GET", headers: Mapping[str, str] | None = None, data: bytes | None = None, timeout: float = 8.0) -> HttpResponse:
        request = urllib.request.Request(url, data=data, headers=dict(headers or {}), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read(), dict(response.headers.items()))
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, error.read(), dict(error.headers.items()))


class OpenSkyError(RuntimeError):
    pass


class AuthenticationError(OpenSkyError):
    pass


class RateLimitError(OpenSkyError):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("OpenSky rate limit reached")
        self.retry_after = retry_after


class TokenManager:
    def __init__(self, config: OpenSkyConfig, transport: HttpTransport, clock=time.monotonic) -> None:
        self.config = config
        self.transport = transport
        self.clock = clock
        self._token = ""
        self._expires_at = 0.0

    def get(self) -> str:
        now = self.clock()
        if self._token and now < self._expires_at - 60.0:
            return self._token
        form = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            }
        ).encode("ascii")
        response = self.transport.request(
            TOKEN_URL,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=form,
            timeout=self.config.timeout_seconds,
        )
        if response.status != 200:
            raise AuthenticationError(f"OpenSky authentication returned HTTP {response.status}")
        try:
            payload = json.loads(response.body)
            token = payload["access_token"]
            expires_in = float(payload.get("expires_in", 1800))
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AuthenticationError("OpenSky authentication response has an invalid schema") from error
        if not isinstance(token, str) or not token or not 60 <= expires_in <= 86400:
            raise AuthenticationError("OpenSky authentication response has invalid token fields")
        self._token = token
        self._expires_at = now + expires_in
        LOG.info("OpenSky access token acquired; expires in %.0f seconds", expires_in)
        return token

    def invalidate(self) -> None:
        self._token = ""
        self._expires_at = 0.0


def bounding_box(geometry: RadarGeometry) -> dict[str, float]:
    latitude_delta = math.degrees(geometry.radius_km / EARTH_RADIUS_KM)
    cosine = max(0.01, abs(math.cos(math.radians(geometry.latitude))))
    longitude_delta = math.degrees(geometry.radius_km / (EARTH_RADIUS_KM * cosine))
    return {
        "lamin": max(-90.0, geometry.latitude - latitude_delta),
        "lamax": min(90.0, geometry.latitude + latitude_delta),
        "lomin": max(-180.0, geometry.longitude - longitude_delta),
        "lomax": min(180.0, geometry.longitude + longitude_delta),
    }


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def parse_states(body: bytes, geometry: RadarGeometry) -> list[AircraftView]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenSkyError("OpenSky response is not valid JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("states"), list):
        raise OpenSkyError("OpenSky response has an invalid schema")

    aircraft: list[AircraftView] = []
    for state in payload["states"]:
        if not isinstance(state, list) or len(state) < 17:
            continue
        icao24 = state[0]
        if not isinstance(icao24, str) or not icao24:
            continue
        longitude = _finite_number(state[5])
        latitude = _finite_number(state[6])
        if longitude is None or latitude is None or not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        if not geometry.contains(latitude, longitude):
            continue
        heading = _finite_number(state[10])
        velocity = _finite_number(state[9])
        altitude = _finite_number(state[7])
        vertical_rate = _finite_number(state[11])
        last_contact = _finite_number(state[4])
        if heading is None:
            heading = 0.0
        heading %= 360.0
        if velocity is not None and not 0 <= velocity <= 400:
            velocity = None
        if altitude is not None and not -1000 <= altitude <= 25000:
            altitude = None
        if vertical_rate is not None and not -150 <= vertical_rate <= 150:
            vertical_rate = None
        callsign = state[1].strip() if isinstance(state[1], str) else ""
        aircraft.append(
            AircraftView(
                icao24=icao24.lower(),
                callsign=callsign,
                latitude=latitude,
                longitude=longitude,
                heading=heading,
                altitude_m=altitude,
                velocity_mps=velocity,
                vertical_rate_mps=vertical_rate,
                on_ground=state[8] if isinstance(state[8], bool) else False,
                last_contact_epoch=last_contact,
            )
        )
    return aircraft


class OpenSkyClient:
    def __init__(self, config: OpenSkyConfig, geometry: RadarGeometry, transport: HttpTransport | None = None, clock=time.monotonic) -> None:
        self.config = config
        self.geometry = geometry
        self.transport = transport or UrllibTransport()
        self.tokens = TokenManager(config, self.transport, clock)

    def fetch(self) -> list[AircraftView]:
        geometry = self.geometry
        token = self.tokens.get()
        query = urllib.parse.urlencode(bounding_box(geometry))
        response = self.transport.request(
            f"{STATES_URL}?{query}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=self.config.timeout_seconds,
        )
        if response.status == 401:
            self.tokens.invalidate()
            raise AuthenticationError("OpenSky states request returned HTTP 401")
        if response.status == 429:
            raw_retry = response.headers.get("Retry-After")
            try:
                retry_after = float(raw_retry) if raw_retry is not None else None
            except ValueError:
                retry_after = None
            raise RateLimitError(retry_after)
        if response.status != 200:
            raise OpenSkyError(f"OpenSky states request returned HTTP {response.status}")
        return parse_states(response.body, geometry)

    def set_geometry(self, geometry: RadarGeometry) -> None:
        self.geometry = geometry


@dataclass(frozen=True)
class OpenSkySnapshot:
    aircraft: tuple[AircraftView, ...] = ()
    status: str = "CONFIG"
    last_success_monotonic: float | None = None


class OpenSkyDataLayer:
    def __init__(self, config: OpenSkyConfig, geometry: RadarGeometry, client: OpenSkyClient | None = None, clock=time.monotonic) -> None:
        self.config = config
        self.client = client or OpenSkyClient(config, geometry)
        self.clock = clock
        self._lock = threading.Lock()
        self._snapshot = OpenSkySnapshot()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.client_id or not self.config.client_secret:
            LOG.warning("OpenSky credentials are not configured")
            return
        self._thread = threading.Thread(target=self._run, name="opensky-fetch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.config.timeout_seconds + 2)

    def snapshot(self) -> OpenSkySnapshot:
        with self._lock:
            return self._snapshot

    def set_geometry(self, geometry: RadarGeometry) -> None:
        self.client.set_geometry(geometry)

    def _set_status(self, status: str, aircraft: tuple[AircraftView, ...] | None = None) -> None:
        with self._lock:
            previous = self._snapshot
            self._snapshot = OpenSkySnapshot(
                aircraft=previous.aircraft if aircraft is None else aircraft,
                status=status,
                last_success_monotonic=previous.last_success_monotonic if aircraft is None else self.clock(),
            )

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            wait_seconds = float(self.config.poll_interval_seconds)
            try:
                result = tuple(self.client.fetch())
                self._set_status("OK", result)
                failures = 0
                LOG.info("OpenSky update successful: %d aircraft", len(result))
            except RateLimitError as error:
                failures += 1
                wait_seconds = max(error.retry_after or 0.0, min(900.0, 15.0 * (2 ** min(failures, 6))))
                self._set_status("RATE")
                LOG.warning("OpenSky rate limited; retrying in %.0f seconds", wait_seconds)
            except AuthenticationError:
                failures += 1
                wait_seconds = min(900.0, 30.0 * (2 ** min(failures, 5)))
                self._set_status("AUTH")
                LOG.warning("OpenSky authentication failed; retrying in %.0f seconds", wait_seconds)
            except Exception as error:
                failures += 1
                base = min(300.0, 5.0 * (2 ** min(failures - 1, 6)))
                wait_seconds = base * random.uniform(0.85, 1.15)
                self._set_status("ERROR")
                LOG.warning("OpenSky update failed (%s); retrying in %.0f seconds", type(error).__name__, wait_seconds)
            self._stop.wait(wait_seconds)
