from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("/etc/picket-virtual-radar/config.json")


@dataclass(frozen=True)
class DisplayConfig:
    device: str = "/dev/fb0"
    width: int = 320
    height: int = 240
    fps: int = 30
    update_mode: str = "full"
    brightness_percent: int = 80


@dataclass(frozen=True)
class RuntimeConfig:
    logic_hz: int = 10
    log_level: str = "INFO"


@dataclass(frozen=True)
class RadarConfig:
    latitude: float = 25.080278
    longitude: float = 121.232222
    radius_km: float = 50.0


@dataclass(frozen=True)
class OpenSkyConfig:
    client_id: str = ""
    client_secret: str = ""
    poll_interval_seconds: int = 15
    timeout_seconds: int = 8


@dataclass(frozen=True)
class TrackingConfig:
    interpolation_seconds: float = 2.0
    prediction_seconds: float = 20.0
    stale_after_seconds: float = 90.0
    show_on_ground: bool = False


@dataclass(frozen=True)
class TouchConfig:
    device_name: str = "EP0110M09"
    rotation: int = 90
    tap_max_seconds: float = 0.35
    long_press_seconds: float = 0.7
    move_tolerance_px: int = 12
    swipe_min_px: int = 40


@dataclass(frozen=True)
class UiConfig:
    info_mode: str = "callsign"
    show_scanline: bool = True
    show_aircraft_heading: bool = True
    show_data_age: bool = True
    show_altitude: bool = True
    show_speed: bool = True
    highlight_callsigns: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalizationConfig:
    distance_unit: str = "km"
    altitude_unit: str = "m"
    speed_unit: str = "kt"
    timezone: str = "Asia/Taipei"


@dataclass(frozen=True)
class WebConfig:
    enabled: bool = True
    port: int = 8080
    access_token: str = ""


@dataclass(frozen=True)
class WifiConfig:
    fallback_enabled: bool = True
    interface: str = "wlan0"
    hotspot_ssid: str = "PIcketRadar-Setup"
    hotspot_password: str = "picket-radar"
    gateway: str = "192.168.4.1"
    fallback_after_seconds: int = 45
    connection_timeout_seconds: int = 45
    hotspot_timeout_seconds: int = 900
    reset_button_gpio: int = 17
    reset_hold_seconds: int = 8


@dataclass(frozen=True)
class AppConfig:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    radar: RadarConfig = field(default_factory=RadarConfig)
    opensky: OpenSkyConfig = field(default_factory=OpenSkyConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    touch: TouchConfig = field(default_factory=TouchConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    localization: LocalizationConfig = field(default_factory=LocalizationConfig)
    web: WebConfig = field(default_factory=WebConfig)
    wifi: WifiConfig = field(default_factory=WifiConfig)


def _require_int(data: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _require_float(data: dict[str, Any], key: str, default: float, minimum: float, maximum: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return result


def _require_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def normalize_callsign(value: str) -> str:
    return "".join(value.upper().split())


def _require_highlight_callsigns(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("highlight_callsigns", [])
    if not isinstance(raw, list) or len(raw) > 3 or not all(isinstance(item, str) for item in raw):
        raise ValueError("ui.highlight_callsigns must be a list of at most 3 strings")
    normalized: list[str] = []
    for item in raw:
        callsign = normalize_callsign(item)
        if not callsign:
            continue
        if len(callsign) > 12 or not all(character.isascii() and (character.isalnum() or character in "-_") for character in callsign):
            raise ValueError("highlight callsigns must use at most 12 ASCII letters, digits, '-' or '_'")
        if callsign not in normalized:
            normalized.append(callsign)
    return tuple(normalized)


def load_config(path: Path | None = None) -> AppConfig:
    selected = path or Path(os.environ.get("PVR_CONFIG", DEFAULT_CONFIG_PATH))
    if not selected.exists():
        return AppConfig()

    with selected.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be an object")

    display_raw = raw.get("display", {})
    runtime_raw = raw.get("runtime", {})
    radar_raw = raw.get("radar", {})
    opensky_raw = raw.get("opensky", {})
    tracking_raw = raw.get("tracking", {})
    touch_raw = raw.get("touch", {})
    ui_raw = raw.get("ui", {})
    localization_raw = raw.get("localization", {})
    web_raw = raw.get("web", {})
    wifi_raw = raw.get("wifi", {})
    if not all(isinstance(item, dict) for item in (display_raw, runtime_raw, radar_raw, opensky_raw, tracking_raw, touch_raw, ui_raw, localization_raw, web_raw, wifi_raw)):
        raise ValueError("configuration sections must be objects")

    device = display_raw.get("device", "/dev/fb0")
    log_level = runtime_raw.get("log_level", "INFO")
    if not isinstance(device, str) or not device.startswith("/dev/fb"):
        raise ValueError("display.device must be a framebuffer device")
    if not isinstance(log_level, str):
        raise ValueError("runtime.log_level must be a string")
    client_id = opensky_raw.get("client_id", "")
    client_secret = opensky_raw.get("client_secret", "")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise ValueError("OpenSky credentials must be strings")
    device_name = touch_raw.get("device_name", "EP0110M09")
    if not isinstance(device_name, str) or not device_name.strip():
        raise ValueError("touch.device_name must be a non-empty string")
    rotation = touch_raw.get("rotation", 90)
    if rotation not in {90, 270}:
        raise ValueError("touch.rotation must be 90 or 270")
    info_mode = ui_raw.get("info_mode", "callsign")
    if info_mode not in {"callsign", "details", "hidden"}:
        raise ValueError("ui.info_mode must be callsign, details or hidden")
    distance_unit = localization_raw.get("distance_unit", "km")
    altitude_unit = localization_raw.get("altitude_unit", "m")
    speed_unit = localization_raw.get("speed_unit", "kt")
    timezone = localization_raw.get("timezone", "Asia/Taipei")
    if distance_unit not in {"km", "nm"} or altitude_unit not in {"m", "ft"} or speed_unit not in {"kt", "kmh"}:
        raise ValueError("invalid localization unit")
    if not isinstance(timezone, str) or not timezone or ".." in timezone:
        raise ValueError("invalid timezone")
    access_token = web_raw.get("access_token", "")
    if not isinstance(access_token, str):
        raise ValueError("web.access_token must be a string")
    wifi_interface = wifi_raw.get("interface", "wlan0")
    hotspot_ssid = wifi_raw.get("hotspot_ssid", "PIcketRadar-Setup")
    hotspot_password = wifi_raw.get("hotspot_password", "picket-radar")
    gateway = wifi_raw.get("gateway", "192.168.4.1")
    if not isinstance(wifi_interface, str) or not wifi_interface:
        raise ValueError("wifi.interface must be a non-empty string")
    if not isinstance(hotspot_ssid, str) or not 1 <= len(hotspot_ssid) <= 32:
        raise ValueError("wifi.hotspot_ssid must contain 1 to 32 characters")
    if not isinstance(hotspot_password, str) or not 8 <= len(hotspot_password) <= 63:
        raise ValueError("wifi.hotspot_password must contain 8 to 63 characters")
    if not isinstance(gateway, str) or gateway.count(".") != 3:
        raise ValueError("wifi.gateway must be an IPv4 address")
    update_mode = display_raw.get("update_mode", "full")
    if update_mode not in {"full", "dirty"}:
        raise ValueError("display.update_mode must be 'full' or 'dirty'")

    return AppConfig(
        display=DisplayConfig(
            device=device,
            width=_require_int(display_raw, "width", 320, 1, 4096),
            height=_require_int(display_raw, "height", 240, 1, 4096),
            fps=_require_int(display_raw, "fps", 30, 1, 120),
            update_mode=update_mode,
            brightness_percent=_require_int(display_raw, "brightness_percent", 80, 10, 100),
        ),
        runtime=RuntimeConfig(
            logic_hz=_require_int(runtime_raw, "logic_hz", 10, 1, 100),
            log_level=log_level.upper(),
        ),
        radar=RadarConfig(
            latitude=_require_float(radar_raw, "latitude", 25.080278, -90.0, 90.0),
            longitude=_require_float(radar_raw, "longitude", 121.232222, -180.0, 180.0),
            radius_km=_require_float(radar_raw, "radius_km", 50.0, 1.0, 500.0),
        ),
        opensky=OpenSkyConfig(
            client_id=client_id.strip(),
            client_secret=client_secret,
            poll_interval_seconds=_require_int(opensky_raw, "poll_interval_seconds", 15, 10, 3600),
            timeout_seconds=_require_int(opensky_raw, "timeout_seconds", 8, 2, 60),
        ),
        tracking=TrackingConfig(
            interpolation_seconds=_require_float(tracking_raw, "interpolation_seconds", 2.0, 0.0, 30.0),
            prediction_seconds=_require_float(tracking_raw, "prediction_seconds", 20.0, 0.0, 120.0),
            stale_after_seconds=_require_float(tracking_raw, "stale_after_seconds", 90.0, 10.0, 600.0),
            show_on_ground=_require_bool(tracking_raw, "show_on_ground", False),
        ),
        touch=TouchConfig(
            device_name=device_name.strip(),
            rotation=rotation,
            tap_max_seconds=_require_float(touch_raw, "tap_max_seconds", 0.35, 0.1, 1.0),
            long_press_seconds=_require_float(touch_raw, "long_press_seconds", 0.7, 0.4, 2.0),
            move_tolerance_px=_require_int(touch_raw, "move_tolerance_px", 12, 3, 40),
            swipe_min_px=_require_int(touch_raw, "swipe_min_px", 40, 20, 150),
        ),
        ui=UiConfig(
            info_mode=info_mode,
            show_scanline=_require_bool(ui_raw, "show_scanline", True),
            show_aircraft_heading=_require_bool(ui_raw, "show_aircraft_heading", True),
            show_data_age=_require_bool(ui_raw, "show_data_age", True),
            show_altitude=_require_bool(ui_raw, "show_altitude", True),
            show_speed=_require_bool(ui_raw, "show_speed", True),
            highlight_callsigns=_require_highlight_callsigns(ui_raw),
        ),
        localization=LocalizationConfig(
            distance_unit=distance_unit,
            altitude_unit=altitude_unit,
            speed_unit=speed_unit,
            timezone=timezone,
        ),
        web=WebConfig(
            enabled=_require_bool(web_raw, "enabled", True),
            port=_require_int(web_raw, "port", 8080, 1024, 65535),
            access_token=access_token,
        ),
        wifi=WifiConfig(
            fallback_enabled=_require_bool(wifi_raw, "fallback_enabled", True),
            interface=wifi_interface,
            hotspot_ssid=hotspot_ssid,
            hotspot_password=hotspot_password,
            gateway=gateway,
            fallback_after_seconds=_require_int(wifi_raw, "fallback_after_seconds", 45, 15, 600),
            connection_timeout_seconds=_require_int(wifi_raw, "connection_timeout_seconds", 45, 15, 180),
            hotspot_timeout_seconds=_require_int(wifi_raw, "hotspot_timeout_seconds", 900, 60, 86400),
            reset_button_gpio=_require_int(wifi_raw, "reset_button_gpio", 17, 0, 27),
            reset_hold_seconds=_require_int(wifi_raw, "reset_hold_seconds", 8, 3, 30),
        ),
    )
