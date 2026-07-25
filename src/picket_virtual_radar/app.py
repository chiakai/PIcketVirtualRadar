from __future__ import annotations

import logging
import math
import signal
import socket
import threading
import time

from .config import AppConfig
from .backlight import BacklightController
from .config_recovery import confirm_start
from .display import FramebufferDisplay
from .geometry import RadarGeometry
from .gps import UsbGpsReader
from .opensky import OpenSkyDataLayer
from .radar_renderer import RadarRenderer
from .settings_store import update_settings
from .touch import Gesture, TouchInput
from .tracking import AircraftTracker
from .web_server import SettingsWebServer, ensure_access_token
from .wifi_manager import WifiManager
from .system_health import HealthMonitor, HelpButton, ShutdownButton, SystemdNotifier


LOG = logging.getLogger(__name__)


class RadarApplication:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.stop_event = threading.Event()
        self.logic_ticks = 0
        self.renderer: RadarRenderer | None = None
        self.geometry = RadarGeometry(
            latitude=config.radar.latitude,
            longitude=config.radar.longitude,
            radius_km=config.radar.radius_km,
        )
        self.display_geometry = self.geometry
        self.display_zoom = 1.0
        self._last_range_tap = 0.0
        self.data_layer = OpenSkyDataLayer(config.opensky, self.geometry)
        self.gps_reader = UsbGpsReader(config.gps)
        self.centre_source = "CONFIG"
        self.tracker = AircraftTracker(config.tracking)
        self._last_ingested_snapshot: float | None = None
        self.api_status = "CONFIG"
        self.selected_icao: str | None = None
        self.overlay: str | None = None
        self.ui_options = {
            "info_mode": config.ui.info_mode,
            "show_scanline": config.ui.show_scanline,
            "show_aircraft_heading": config.ui.show_aircraft_heading,
            "show_data_age": config.ui.show_data_age,
            "show_on_ground": config.tracking.show_on_ground,
            "show_altitude": config.ui.show_altitude,
            "show_speed": config.ui.show_speed,
            "highlight_callsigns": config.ui.highlight_callsigns,
            "altitude_unit": config.localization.altitude_unit,
            "speed_unit": config.localization.speed_unit,
        }
        self.touch = TouchInput(
            config.touch, config.display.width, config.display.height
        )
        self.backlight = BacklightController(config.display.brightness_percent)
        self.system_info = self._system_info()
        self.wifi_manager = WifiManager(config.wifi)
        self.health_monitor = HealthMonitor()
        self.shutdown_button = ShutdownButton()
        self.help_button = HelpButton()
        self.help_scroll = 0
        self.notifier = SystemdNotifier()
        self.web_server: SettingsWebServer | None = None
        if config.web.enabled:
            self.web_token = ensure_access_token(config)
            self.system_info["url"] = f"http://{self.system_info['ip']}:{config.web.port}/"
            self.system_info["token"] = f"?token={self.web_token}"
            self.web_server = SettingsWebServer(config, self.web_token, self.stop_event.set, self.wifi_manager)

    @staticmethod
    def _system_info() -> dict[str, str]:
        hostname = socket.gethostname()
        ip_address = "--"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
                connection.connect(("1.1.1.1", 80))
                ip_address = connection.getsockname()[0]
        except OSError:
            pass
        return {
            "hostname": hostname,
            "ip": ip_address,
            "url": f"http://{ip_address}" if ip_address != "--" else "--",
        }

    def request_stop(self, signum: int, _frame: object) -> None:
        LOG.info("shutdown requested", extra={"signal": signum})
        self.stop_event.set()

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

    def update(self, elapsed: float) -> None:
        del elapsed
        self.logic_ticks += 1
        self._update_gps_centre()
        snapshot = self.data_layer.snapshot()
        self.api_status = snapshot.status
        if (
            snapshot.last_success_monotonic is not None
            and snapshot.last_success_monotonic != self._last_ingested_snapshot
        ):
            self.tracker.ingest(snapshot.aircraft)
            self._last_ingested_snapshot = snapshot.last_success_monotonic
        else:
            self.tracker.prune()
        views = self.tracker.views()
        if self.selected_icao is not None and not any(item.icao24 == self.selected_icao for item in views):
            self.selected_icao = None
        for gesture in self.touch.poll():
            LOG.info(
                "touch gesture: %s x=%d y=%d%s",
                gesture.kind,
                gesture.x,
                gesture.y,
                f" direction={gesture.direction}" if gesture.direction else "",
            )
            self._handle_gesture(gesture, views)

    def _update_gps_centre(self) -> None:
        gps = self.gps_reader.snapshot()
        use_gps = gps.status == "FIX" and gps.latitude is not None and gps.longitude is not None
        latitude = gps.latitude if use_gps else self.config.radar.latitude
        longitude = gps.longitude if use_gps else self.config.radar.longitude
        source = "GPS" if use_gps else ("GPS WAIT" if self.config.gps.enabled else "CONFIG")
        self.system_info["gps_status"] = gps.status
        self.system_info["gps_device"] = gps.device
        self.system_info["centre_source"] = source
        self.system_info["centre_latitude"] = f"{latitude:.6f}"
        self.system_info["centre_longitude"] = f"{longitude:.6f}"
        if source == self.centre_source and abs(latitude - self.geometry.latitude) < 1e-7 and abs(longitude - self.geometry.longitude) < 1e-7:
            return
        self.centre_source = source
        self.geometry = RadarGeometry(
            latitude=latitude,
            longitude=longitude,
            radius_km=self.config.radar.radius_km,
        )
        self.display_geometry = RadarGeometry(
            latitude=latitude,
            longitude=longitude,
            radius_km=self.config.radar.radius_km * self.display_zoom,
        )
        self.data_layer.set_geometry(self.geometry)
        self.renderer = None
        LOG.info("radar centre changed: %.6f, %.6f source=%s", latitude, longitude, source)

    def _persist_options(self) -> None:
        try:
            update_settings(
                {
                    "ui": {
                        "info_mode": self.ui_options["info_mode"],
                        "show_scanline": self.ui_options["show_scanline"],
                        "show_aircraft_heading": self.ui_options["show_aircraft_heading"],
                        "show_data_age": self.ui_options["show_data_age"],
                        "show_altitude": self.ui_options["show_altitude"],
                        "show_speed": self.ui_options["show_speed"],
                    },
                    "tracking": {"show_on_ground": self.ui_options["show_on_ground"]},
                }
            )
        except Exception:
            LOG.exception("failed to save touch UI settings")

    def _ordered_aircraft(self, views: tuple) -> list:
        def distance(item: object) -> float:
            east, north = self.geometry.local_km(item.latitude, item.longitude)
            return math.hypot(east, north)
        return sorted(views, key=distance)

    def _select_at(self, x: int, y: int, views: tuple) -> None:
        nearest = None
        nearest_distance = 22.0
        for item in views:
            screen_x, screen_y = self.display_geometry.to_screen(item.latitude, item.longitude)
            distance = math.hypot(x - screen_x, y - screen_y)
            if (
                self.ui_options["info_mode"] != "hidden"
                and screen_x + 5 <= x <= screen_x + 70
                and screen_y - 12 <= y <= screen_y + 12
            ):
                distance = 0.0
            if distance <= nearest_distance:
                nearest = item
                nearest_distance = distance
        self.selected_icao = None if nearest is None else nearest.icao24

    def _cycle_selection(self, direction: str, views: tuple) -> None:
        ordered = self._ordered_aircraft(views)
        if not ordered or self.selected_icao is None:
            return
        identifiers = [item.icao24 for item in ordered]
        try:
            index = identifiers.index(self.selected_icao)
        except ValueError:
            return
        step = 1 if direction == "left" else -1
        self.selected_icao = identifiers[(index + step) % len(identifiers)]

    def _toggle_quick_setting(self, y: int) -> None:
        if y >= 198:
            self.overlay = None
            return
        if y < 34:
            return
        index = (y - 34) // 40
        if index == 0:
            self.ui_options["show_scanline"] = not self.ui_options["show_scanline"]
        elif index == 1:
            self.ui_options["show_aircraft_heading"] = not self.ui_options["show_aircraft_heading"]
        elif index == 2:
            self.ui_options["info_mode"] = "hidden" if self.ui_options["info_mode"] != "hidden" else "callsign"
        elif index == 3:
            enabled = not self.ui_options["show_on_ground"]
            self.ui_options["show_on_ground"] = enabled
            self.tracker.set_show_on_ground(enabled)
            if enabled:
                self.tracker.ingest(self.data_layer.snapshot().aircraft)
        else:
            return
        self._persist_options()

    def _handle_range_tap(self, now: float) -> None:
        if now - self._last_range_tap <= 0.5:
            self.display_zoom = 0.5 if self.display_zoom == 1.0 else 1.0
            self.display_geometry = RadarGeometry(
                latitude=self.geometry.latitude,
                longitude=self.geometry.longitude,
                radius_km=self.config.radar.radius_km * self.display_zoom,
            )
            self.renderer = None
            LOG.info(
                "radar display zoom changed: %.0f%%, display radius %.1f km; API radius remains %.1f km",
                self.display_zoom * 100,
                self.display_geometry.radius_km,
                self.geometry.radius_km,
            )
            self._last_range_tap = 0.0
        else:
            self._last_range_tap = now

    def _handle_gesture(self, gesture: Gesture, views: tuple) -> None:
        if self.overlay == "help":
            if gesture.kind == "swipe" and gesture.direction in {"up", "down"}:
                step = 5 if gesture.direction == "up" else -5
                self.help_scroll = max(0, min(self.help_scroll + step, RadarRenderer.help_scroll_limit()))
            return
        if self.overlay == "quick":
            if gesture.kind == "tap":
                self._toggle_quick_setting(gesture.y)
            return
        if self.overlay == "info":
            if gesture.kind == "tap":
                self.overlay = None
            return
        if gesture.kind == "tap" and 184 <= gesture.x < 240 and gesture.y >= 202:
            self._handle_range_tap(time.monotonic())
            return
        if gesture.kind == "long_press":
            self.overlay = "info" if gesture.x >= 240 else "quick"
        elif gesture.kind == "swipe" and gesture.direction in {"left", "right"}:
            self._cycle_selection(gesture.direction or "left", views)
        elif gesture.kind == "tap" and gesture.x >= 240:
            modes = ("callsign", "details", "hidden")
            current = modes.index(self.ui_options["info_mode"])
            self.ui_options["info_mode"] = modes[(current + 1) % len(modes)]
            self._persist_options()
        elif gesture.kind == "tap":
            self._select_at(gesture.x, gesture.y, views)

    def draw(self, display: FramebufferDisplay, elapsed: float) -> list[object] | None:
        if self.renderer is None:
            self.renderer = RadarRenderer(
                display.pygame,
                display.surface.get_size(),
                self.display_geometry,
                self.config.localization.distance_unit,
            )
        wifi = self.wifi_manager.status()
        health = self.health_monitor.status()
        if wifi.ip != "--":
            self.system_info["ip"] = wifi.ip
            self.system_info["url"] = f"http://{wifi.ip}:{self.config.web.port}/"
        self.system_info["wifi_mode"] = wifi.mode
        self.system_info["wifi_ssid"] = wifi.ssid
        self.system_info["wifi_signal"] = "" if wifi.signal_percent is None else str(wifi.signal_percent)
        self.system_info["wifi_password"] = self.config.wifi.hotspot_password if wifi.mode == "AP" else ""
        self.system_info["temperature"] = "--" if health.temperature_c is None else f"{health.temperature_c:.0f}C"
        self.system_info["health_warning"] = health.warning
        return self.renderer.render(
            display.surface,
            elapsed,
            self.tracker.views(),
            self.api_status,
            self.selected_icao,
            self.ui_options,
            "wifi" if wifi.mode == "AP" else self.overlay,
            {
                **self.system_info,
                "api": self.api_status,
                "aircraft": str(self.tracker.count),
                "help_scroll": str(self.help_scroll),
            },
        )

    def run(self) -> int:
        self.install_signal_handlers()
        display_cfg = self.config.display
        logic_interval = 1.0 / self.config.runtime.logic_hz
        frame_interval = 1.0 / display_cfg.fps
        start = time.monotonic()
        previous_logic = start
        next_logic = start
        next_frame = start
        frames = 0
        settings_confirmed = False
        LOG.info(
            "application starting: %sx%s at %s FPS, logic %s Hz",
            display_cfg.width,
            display_cfg.height,
            display_cfg.fps,
            self.config.runtime.logic_hz,
        )

        try:
            self.data_layer.start()
            self.gps_reader.start()
            self.backlight.open()
            self.touch.open()
            self.wifi_manager.start()
            self.shutdown_button.open()
            self.help_button.open()
            if self.web_server is not None:
                self.web_server.start()
            with FramebufferDisplay(
                display_cfg.device, display_cfg.width, display_cfg.height
            ) as display:
                self.notifier.ready()
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    self.notifier.watchdog(now)
                    if self.shutdown_button.poll(now):
                        self.stop_event.set()
                    if self.help_button.poll(now):
                        self.overlay = None if self.overlay == "help" else "help"
                        self.help_scroll = 0
                    if not settings_confirmed and now - start >= 15.0:
                        try:
                            confirm_start()
                        except OSError:
                            LOG.exception("failed to confirm healthy settings")
                        settings_confirmed = True
                    while now >= next_logic:
                        self.update(now - previous_logic)
                        previous_logic = now
                        next_logic += logic_interval
                    if now >= next_frame:
                        dirty = self.draw(display, now - start)
                        display.present(dirty if display_cfg.update_mode == "dirty" else None)
                        frames += 1
                        next_frame += frame_interval
                        if now - next_frame > frame_interval:
                            next_frame = now + frame_interval
                    wait_until = min(next_logic, next_frame)
                    self.stop_event.wait(max(0.0, wait_until - time.monotonic()))
        except Exception:
            LOG.exception("application stopped unexpectedly")
            return 1
        finally:
            self.notifier.stopping()
            if self.web_server is not None:
                self.web_server.stop()
            self.touch.close()
            self.wifi_manager.stop()
            self.shutdown_button.close()
            self.help_button.close()
            self.backlight.close()
            self.data_layer.stop()
            self.gps_reader.stop()

        elapsed = time.monotonic() - start
        LOG.info(
            "application stopped cleanly after %.2fs, frames=%d, logic_ticks=%d, framebuffer_bytes=%d",
            elapsed,
            frames,
            self.logic_ticks,
            display.bytes_presented,
        )
        return 0
