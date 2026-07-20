from __future__ import annotations

import math
from typing import Any, Iterable

from .geometry import RadarGeometry
from .models import AircraftView
from .config import normalize_callsign


RADAR_SIZE = 240
PANEL_LEFT = 240
PANEL_WIDTH = 80
HELP_VISIBLE_LINES = 13
HELP_LINES = (
    "TOUCH CONTROLS",
    "Tap aircraft: select",
    "Tap blank: clear selection",
    "Tap side panel: info mode",
    "Swipe L/R: select aircraft",
    "Double-tap RANGE: zoom",
    "Long-press radar: quick menu",
    "Long-press panel: system info",
    "",
    "QUICK SETTINGS",
    "Toggle scanline / heading",
    "Toggle callsign / ground A/C",
    "",
    "PHYSICAL BUTTONS",
    "Button 1 / GPIO17 hold 8s:",
    "  reset Wi-Fi and start AP",
    "Button 2 / GPIO22 hold 3s:",
    "  safe system shutdown",
    "Button 3 / GPIO23: unused",
    "Button 4 / GPIO27: Help on/off",
    "",
    "RADAR DISPLAY",
    "Red aircraft: watched flight",
    "Cyan ring: selected aircraft",
    "A: live age  P: predicted age",
    "STATUS: network state",
    "API: OpenSky state",
    "WiFi bars / Ethernet: link",
    "",
    "WEB SETTINGS",
    "Scan QR in System / Settings",
    "Configure radar, API, display,",
    "watched flights, units, Wi-Fi",
)


def aircraft_is_highlighted(callsign: str, highlight_callsigns: set[str]) -> bool:
    return bool(callsign) and normalize_callsign(callsign) in highlight_callsigns


class RadarRenderer:
    @staticmethod
    def help_scroll_limit() -> int:
        return max(0, len(HELP_LINES) - HELP_VISIBLE_LINES)

    def __init__(self, pygame: Any, size: tuple[int, int], geometry: RadarGeometry, distance_unit: str = "km") -> None:
        self.pygame = pygame
        self.geometry = geometry
        self.size = size
        self.distance_unit = distance_unit
        self.font = pygame.font.Font(None, 14)
        self.small_font = pygame.font.Font(None, 12)
        self.background = pygame.Surface(
            size, depth=16, masks=(0xF800, 0x07E0, 0x001F, 0)
        )
        self._previous_sweep: tuple[int, int] | None = None
        self._previous_aircraft_rects: list[Any] = []
        self._first_frame = True
        self._qr_payload = ""
        self._qr_matrix: tuple[tuple[bool, ...], ...] = ()
        self._draw_static_background()

    def _text(self, target: Any, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
        target.blit(self.font.render(text, True, color), (x, y))

    def _text_right(self, target: Any, text: str, right: int, y: int, color: tuple[int, int, int]) -> None:
        rendered = self.font.render(text, True, color)
        target.blit(rendered, (right - rendered.get_width(), y))

    def _draw_static_background(self) -> None:
        p = self.pygame
        target = self.background
        target.fill((0, 7, 0))
        centre = (int(self.geometry.centre_x), int(self.geometry.centre_y))
        radius = int(self.geometry.pixel_radius)
        for fraction, color in ((1.0, (0, 150, 45)), (2 / 3, (0, 76, 25)), (1 / 3, (0, 55, 18))):
            p.draw.circle(target, color, centre, int(radius * fraction), 1)
        p.draw.line(target, (0, 45, 14), (centre[0] - radius, centre[1]), (centre[0] + radius, centre[1]))
        p.draw.line(target, (0, 45, 14), (centre[0], centre[1] - radius), (centre[0], centre[1] + radius))
        for degrees in range(0, 360, 30):
            radians = math.radians(degrees)
            outer = (centre[0] + int(math.sin(radians) * radius), centre[1] - int(math.cos(radians) * radius))
            inner_length = radius - (7 if degrees % 90 == 0 else 4)
            inner = (centre[0] + int(math.sin(radians) * inner_length), centre[1] - int(math.cos(radians) * inner_length))
            p.draw.line(target, (0, 180, 55), inner, outer, 1)
        for label, position in (("N", (116, 1)), ("E", (229, 115)), ("S", (117, 226)), ("W", (2, 115))):
            target.blit(self.small_font.render(label, True, (0, 220, 70)), position)
        p.draw.rect(target, (3, 18, 8), (PANEL_LEFT, 0, PANEL_WIDTH, self.size[1]))
        p.draw.line(target, (0, 110, 35), (PANEL_LEFT, 0), (PANEL_LEFT, self.size[1]))
        self._text(target, "PIcket", 4, 2, (0, 255, 80))
        self._text(target, "RADAR", 4, 15, (0, 190, 58))
        self._text(target, "AIRCRAFT", 246, 8, (120, 150, 125))

    def _draw_radar_info(self, target: Any, system_info: dict[str, str]) -> list[Any]:
        p = self.pygame
        rectangles = [p.Rect(0, 0, 70, 31), p.Rect(184, 0, 56, 31), p.Rect(0, 202, 45, 38), p.Rect(188, 207, 52, 33)]
        wifi_mode = system_info.get("wifi_mode", "CHECKING")
        status_color = (0, 235, 75) if wifi_mode in {"CLIENT", "ETHERNET"} else (240, 185, 30) if wifi_mode in {"AP", "CONNECTING"} else (255, 75, 55)
        self._text_right(target, "STATUS", 236, 2, (120, 150, 125))
        self._text_right(target, "ONLINE" if wifi_mode in {"CLIENT", "ETHERNET"} else wifi_mode[:8], 236, 15, status_color)
        distance = self.geometry.radius_km if self.distance_unit == "km" else self.geometry.radius_km / 1.852
        self._text_right(target, "RANGE", 236, 211, (120, 150, 125))
        self._text_right(target, f"{distance:.0f} {self.distance_unit}", 236, 224, (220, 235, 220))
        if wifi_mode == "ETHERNET":
            self._text(target, "Ethernet", 4, 220, (0, 235, 75))
        else:
            self._text(target, "WiFi", 4, 207, (120, 150, 125))
            try:
                signal = max(0, min(100, int(system_info.get("wifi_signal", "0") or 0)))
            except ValueError:
                signal = 0
            active_bars = 0 if signal == 0 else min(6, (signal + 16) // 17)
            for index in range(6):
                box = p.Rect(4 + index * 7, 224, 6, 11)
                if index < active_bars:
                    rectangles.append(p.draw.rect(target, (0, 255, 80), box))
                    p.draw.rect(target, (210, 255, 220), box, 1)
                else:
                    rectangles.append(p.draw.rect(target, (35, 75, 48), box, 1))
        return rectangles

    def _draw_panel(self, target: Any, status: str, aircraft: list[AircraftView], show_data_age: bool, system_info: dict[str, str], highlight_callsigns: set[str]) -> Any:
        panel = self.pygame.Rect(PANEL_LEFT + 1, 0, PANEL_WIDTH - 1, self.size[1])
        target.blit(self.background, panel, panel)
        status_color = (0, 235, 75) if status == "OK" else (240, 185, 30) if status in {"CONFIG", "RATE"} else (255, 75, 55)
        self._text(target, f"API {status[:6]}", 246, 220, status_color)
        warning = system_info.get("health_warning", "")
        if warning and warning != "POWER HISTORY":
            self._text(target, warning[:10], 246, 202, (255, 80, 55))
        self._text(target, str(len(aircraft)), 246, 22, (220, 235, 220))
        if aircraft:
            selected = aircraft[0]
            selected_highlighted = aircraft_is_highlighted(selected.callsign, highlight_callsigns)
            self._text(target, (selected.callsign or selected.icao24)[:9], 246, 35, (255, 55, 55) if selected_highlighted else (220, 235, 220))
            lines = [f"{selected.heading:.0f} deg"]
            if options := getattr(self, "_active_options", None):
                if options["show_altitude"]:
                    if selected.altitude_m is None:
                        lines.append("-- " + options["altitude_unit"])
                    else:
                        altitude = selected.altitude_m if options["altitude_unit"] == "m" else selected.altitude_m * 3.28084
                        lines.append(f"{altitude:.0f} {options['altitude_unit']}")
                if options["show_speed"]:
                    if selected.velocity_mps is None:
                        lines.append("-- " + options["speed_unit"])
                    else:
                        speed = selected.velocity_mps * (1.94384 if options["speed_unit"] == "kt" else 3.6)
                        lines.append(f"{speed:.0f} {options['speed_unit']}")
            for index, line in enumerate(lines[:3]):
                self._text(target, line[:10], 246, 48 + index * 13, (220, 235, 220))
            if show_data_age:
                age_prefix = "P" if selected.predicted else "A"
                self._text(target, f"{age_prefix}:{selected.data_age_seconds:.0f}s", 246, 87, (240, 185, 30) if selected.predicted else (150, 205, 155))
        return panel

    def _line_rectangles(self, start: tuple[int, int], end: tuple[int, int], width: int = 3) -> list[Any]:
        rectangles = []
        segments = 12
        for index in range(segments):
            a = index / segments
            b = (index + 1) / segments
            x1 = round(start[0] + (end[0] - start[0]) * a)
            y1 = round(start[1] + (end[1] - start[1]) * a)
            x2 = round(start[0] + (end[0] - start[0]) * b)
            y2 = round(start[1] + (end[1] - start[1]) * b)
            rectangles.append(self.pygame.Rect(min(x1, x2) - width, min(y1, y2) - width, abs(x2 - x1) + width * 2 + 1, abs(y2 - y1) + width * 2 + 1))
        return rectangles

    def _draw_aircraft(self, target: Any, aircraft: AircraftView, info_mode: str, show_heading: bool, selected: bool, highlighted: bool) -> Any | None:
        if not self.geometry.contains(aircraft.latitude, aircraft.longitude):
            return None
        x, y = self.geometry.to_screen(aircraft.latitude, aircraft.longitude)
        aircraft_color = (255, 55, 55) if highlighted else (255, 215, 45)
        if show_heading:
            heading = math.radians(aircraft.heading)
            points = []
            for offset, length in ((0, 7), (145, 5), (-145, 5)):
                angle = heading + math.radians(offset)
                points.append((round(x + math.sin(angle) * length), round(y - math.cos(angle) * length)))
            rect = self.pygame.draw.polygon(target, aircraft_color, points, 1)
        else:
            rect = self.pygame.draw.circle(target, aircraft_color, (round(x), round(y)), 3, 1)
        if selected:
            rect = rect.union(self.pygame.draw.circle(target, (80, 255, 255), (round(x), round(y)), 10, 1))
        if info_mode != "hidden":
            text = aircraft.callsign.strip() or aircraft.icao24
            if info_mode == "details":
                altitude = "--" if aircraft.altitude_m is None else f"{aircraft.altitude_m:.0f}m"
                text = f"{text} {altitude}"
            label = self.small_font.render(text, True, (255, 55, 55) if highlighted else (190, 255, 190))
            rect = rect.union(target.blit(label, (round(x) + 7, round(y) - 5)))
        return rect.inflate(4, 4)

    def _draw_qr(self, target: Any, payload: str, x: int, y: int, size: int) -> None:
        if not payload or payload.endswith("--"):
            return
        if payload != self._qr_payload:
            try:
                import qrcode
                qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=2)
                qr.add_data(payload)
                qr.make(fit=True)
                self._qr_matrix = tuple(tuple(bool(cell) for cell in row) for row in qr.get_matrix())
                self._qr_payload = payload
            except (ImportError, ValueError):
                self._qr_matrix = ()
                return
        if not self._qr_matrix:
            return
        modules = len(self._qr_matrix)
        scale = max(1, size // modules)
        actual = modules * scale
        left = x + (size - actual) // 2
        top = y + (size - actual) // 2
        self.pygame.draw.rect(target, (255, 255, 255), (x, y, size, size))
        for row, values in enumerate(self._qr_matrix):
            for column, enabled in enumerate(values):
                if enabled:
                    self.pygame.draw.rect(target, (0, 0, 0), (left + column * scale, top + row * scale, scale, scale))

    def _draw_overlay(self, target: Any, overlay: str, options: dict[str, Any], system_info: dict[str, str]) -> None:
        p = self.pygame
        target.fill((2, 15, 7))
        p.draw.rect(target, (0, 180, 55), (2, 2, self.size[0] - 4, self.size[1] - 4), 1)
        if overlay == "help":
            try:
                offset = max(0, min(int(system_info.get("help_scroll", "0")), self.help_scroll_limit()))
            except ValueError:
                offset = 0
            self._text(target, "HELP", 12, 8, (0, 255, 80))
            self._text_right(target, f"{offset + 1}-{min(offset + HELP_VISIBLE_LINES, len(HELP_LINES))}/{len(HELP_LINES)}", 308, 8, (140, 180, 150))
            p.draw.line(target, (0, 110, 35), (10, 24), (310, 24), 1)
            for index, line in enumerate(HELP_LINES[offset : offset + HELP_VISIBLE_LINES]):
                color = (255, 205, 60) if line and line == line.upper() else (210, 230, 215)
                self._text(target, line, 12, 30 + index * 14, color)
            p.draw.line(target, (0, 110, 35), (10, 216), (310, 216), 1)
            self._text(target, "SWIPE UP/DOWN", 12, 220, (140, 180, 150))
            self._text_right(target, "BUTTON 4: CLOSE", 308, 220, (0, 235, 75))
        elif overlay == "quick":
            self._text(target, "QUICK SETTINGS", 12, 8, (0, 255, 80))
            rows = (
                ("SCANLINE", options["show_scanline"]),
                ("HEADING SYMBOL", options["show_aircraft_heading"]),
                ("CALLSIGN", options["info_mode"] != "hidden"),
                ("GROUND AIRCRAFT", options["show_on_ground"]),
            )
            for index, (label, enabled) in enumerate(rows):
                top = 34 + index * 40
                p.draw.rect(target, (5, 32, 14), (10, top, 300, 34))
                self._text(target, label, 20, top + 10, (210, 230, 215))
                self._text(target, "ON" if enabled else "OFF", 270, top + 10, (0, 245, 75) if enabled else (220, 80, 55))
            p.draw.rect(target, (30, 45, 35), (10, 198, 300, 32))
            self._text(target, "CLOSE", 138, 208, (220, 235, 220))
        elif overlay == "wifi":
            self._text(target, "WI-FI SETUP", 12, 10, (255, 200, 40))
            self._text(target, "CONNECT YOUR PHONE TO:", 12, 44, (180, 205, 185))
            self._text(target, system_info.get("wifi_ssid", "PIcketRadar-Setup"), 12, 66, (0, 255, 80))
            self._text(target, "PASSWORD:", 12, 96, (180, 205, 185))
            self._text(target, system_info.get("wifi_password", ""), 12, 116, (0, 255, 80))
            self._text(target, "OPEN IN BROWSER:", 12, 148, (180, 205, 185))
            self._text(target, system_info.get("url", "http://192.168.4.1:8080/"), 12, 168, (0, 255, 80))
            self._text(target, system_info.get("token", ""), 12, 188, (0, 255, 80))
            self._text(target, "BUTTON 1 HOLD 8s: RESET", 12, 218, (255, 180, 45))
        else:
            self._text(target, "SYSTEM / SETTINGS", 12, 10, (0, 255, 80))
            self._text(target, f"HOST: {system_info.get('hostname', '--')}", 12, 42, (210, 230, 215))
            self._text(target, f"IP: {system_info.get('ip', '--')}", 12, 64, (210, 230, 215))
            self._text(target, f"API: {system_info.get('api', '--')}", 12, 86, (210, 230, 215))
            self._text(target, f"AIRCRAFT: {system_info.get('aircraft', '0')}", 12, 108, (210, 230, 215))
            health_warning = system_info.get("health_warning", "")
            power_text = "HISTORY" if health_warning == "POWER HISTORY" else health_warning or "OK"
            health_color = (255, 190, 55) if health_warning else (210, 230, 215)
            self._text(target, f"TEMP: {system_info.get('temperature', '--')}  PWR: {power_text}", 12, 130, health_color)
            self._text(target, "OPEN IN BROWSER:", 12, 158, (120, 160, 130))
            self._text(target, system_info.get("url", "--"), 12, 178, (0, 220, 75))
            self._text(target, system_info.get("token", ""), 12, 196, (0, 220, 75))
            self._draw_qr(target, system_info.get("url", "") + system_info.get("token", ""), 230, 136, 80)
            self._text(target, "TAP TO CLOSE", 110, 218, (160, 185, 165))

    def render(self, target: Any, elapsed: float, aircraft: Iterable[AircraftView], status: str = "CONFIG", selected_icao: str | None = None, options: dict[str, Any] | None = None, overlay: str | None = None, system_info: dict[str, str] | None = None) -> list[Any] | None:
        options = options or {"info_mode": "callsign", "show_scanline": True, "show_aircraft_heading": True, "show_data_age": True, "show_on_ground": False}
        self._active_options = options
        target.blit(self.background, (0, 0))
        dirty: list[Any] = self._draw_radar_info(target, system_info or {})
        aircraft_list = list(aircraft)
        highlight_callsigns = set(options.get("highlight_callsigns", ()))
        dirty.extend(self._previous_aircraft_rects)
        current_aircraft_rects = []
        for item in aircraft_list:
            highlighted = aircraft_is_highlighted(item.callsign, highlight_callsigns)
            rectangle = self._draw_aircraft(target, item, options["info_mode"], options["show_aircraft_heading"], item.icao24 == selected_icao, highlighted)
            if rectangle is not None:
                current_aircraft_rects.append(rectangle)
                dirty.append(rectangle)
        self._previous_aircraft_rects = current_aircraft_rects
        panel_aircraft = [item for item in aircraft_list if item.icao24 == selected_icao]
        dirty.append(self._draw_panel(target, status, panel_aircraft or aircraft_list, options["show_data_age"], system_info or {}, highlight_callsigns))

        centre = (int(self.geometry.centre_x), int(self.geometry.centre_y))
        angle = elapsed * 1.5
        endpoint = (
            centre[0] + round(math.sin(angle) * self.geometry.pixel_radius),
            centre[1] - round(math.cos(angle) * self.geometry.pixel_radius),
        )
        if self._previous_sweep is not None:
            dirty.extend(self._line_rectangles(centre, self._previous_sweep))
        if options["show_scanline"]:
            self.pygame.draw.line(target, (0, 255, 70), centre, endpoint, 2)
            dirty.extend(self._line_rectangles(centre, endpoint))
        self._previous_sweep = endpoint

        if overlay is not None:
            self._draw_overlay(target, overlay, options, system_info or {})
            return None

        if self._first_frame:
            self._first_frame = False
            return None
        return dirty
