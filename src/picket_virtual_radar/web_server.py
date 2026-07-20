from __future__ import annotations

import html
import logging
import secrets
import subprocess
import threading
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .config import AppConfig, normalize_callsign
from .settings_store import update_settings
from .wifi_manager import WifiManager


LOG = logging.getLogger(__name__)


def apply_display_rotation(rotation: int) -> None:
    if rotation not in {90, 270}:
        raise ValueError("Rotation must be 90 or 270 degrees")
    result = subprocess.run(
        ["systemctl", "start", "--wait", f"picket-display-rotate@{rotation}.service"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "no error output"
        raise ValueError(f"Display rotation update failed: {detail}")


def request_system_reboot() -> None:
    result = subprocess.run(
        ["systemctl", "reboot"], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        LOG.error(
            "reboot request failed with exit code %d: %s",
            result.returncode,
            (result.stderr or result.stdout).strip() or "no error output",
        )


def ensure_access_token(config: AppConfig) -> str:
    if config.web.access_token:
        return config.web.access_token
    token = secrets.token_urlsafe(12)
    update_settings({"web": {"access_token": token}})
    return token


def _checked_float(form: dict[str, list[str]], name: str, minimum: float, maximum: float) -> float:
    value = float(form[name][0])
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _checked_int(form: dict[str, list[str]], name: str, minimum: int, maximum: int) -> int:
    value = int(form[name][0])
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _highlight_callsigns(form: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    for index in range(1, 4):
        callsign = normalize_callsign(form.get(f"highlight_callsign_{index}", [""])[0])
        if not callsign:
            continue
        if len(callsign) > 12 or not all(character.isascii() and (character.isalnum() or character in "-_") for character in callsign):
            raise ValueError("Highlighted flight numbers must use at most 12 ASCII letters, digits, '-' or '_'")
        if callsign not in values:
            values.append(callsign)
    return values


def build_handler(
    config: AppConfig,
    token: str,
    request_restart: Callable[[], None],
    wifi_manager: WifiManager | None = None,
    request_reboot: Callable[[], None] = request_system_reboot,
):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PIcketRadar/1"

        def log_message(self, _format: str, *_args: object) -> None:
            LOG.info("web request: %s %s", self.command, self.client_address[0])

        def _authorized(self) -> bool:
            parsed = urllib.parse.urlparse(self.path)
            query_token = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
            jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
            cookie_token = jar.get("pvr_token").value if jar.get("pvr_token") else ""
            return secrets.compare_digest(query_token, token) or secrets.compare_digest(cookie_token, token)

        def _send(self, status: int, body: str, set_cookie: bool = False) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            if set_cookie:
                self.send_header("Set-Cookie", f"pvr_token={token}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(encoded)

        def _form(self) -> dict[str, list[str]]:
            length = min(int(self.headers.get("Content-Length", "0")), 16384)
            return urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)

        def do_GET(self) -> None:
            if not self._authorized():
                self._send(403, "<h1>403</h1><p>Open the URL shown on the radar screen.</p>")
                return
            radius = config.radar.radius_km if config.localization.distance_unit == "km" else config.radar.radius_km / 1.852
            checked = lambda value: " checked" if value else ""
            selected = lambda value, expected: " selected" if value == expected else ""
            wifi_status = wifi_manager.status() if wifi_manager is not None else None
            wifi_options = "".join(
                f"<option value='{html.escape(ssid, quote=True)}'>{html.escape(ssid)} ({signal}% {html.escape(security)})</option>"
                for ssid, signal, security in (wifi_manager.networks() if wifi_manager is not None else ())
                if ssid != config.wifi.hotspot_ssid
            )
            highlight_values = list(config.ui.highlight_callsigns) + [""] * (3 - len(config.ui.highlight_callsigns))
            highlight_inputs = "".join(
                f"<label>Highlighted flight {index + 1}<input name=highlight_callsign_{index + 1} type=text maxlength=12 value='{html.escape(value, quote=True)}' placeholder='e.g. EVA123'></label>"
                for index, value in enumerate(highlight_values)
            )
            page = f"""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>PIcket Radar Settings</title>
<style>body{{font:16px sans-serif;max-width:760px;margin:auto;padding:18px;background:#071009;color:#dce8df}}fieldset{{margin:14px 0;border:1px solid #187c3b}}label{{display:block;margin:10px 0}}input,select,button{{font-size:16px;padding:8px;max-width:100%;box-sizing:border-box}}input[type=text],input[type=password],input[type=number],select{{width:100%}}button{{background:#159447;color:white;border:0;margin:6px 0}}small{{color:#9ab6a2}}.warn{{color:#ffc04d}}</style></head><body><h1>PIcket Virtual Radar</h1>
<form method=post action=/save><input type=hidden name=csrf value='{token}'>
<fieldset><legend>Radar</legend><label>Latitude<input name=latitude type=number step=0.000001 required value='{config.radar.latitude}'></label><label>Longitude<input name=longitude type=number step=0.000001 required value='{config.radar.longitude}'></label><label>Radius ({config.localization.distance_unit.upper()})<input name=radius type=number step=0.1 min=1 required value='{radius:.2f}'></label><label>Distance unit<select name=distance_unit><option value=km{selected(config.localization.distance_unit,'km')}>km</option><option value=nm{selected(config.localization.distance_unit,'nm')}>NM</option></select></label></fieldset>
<fieldset><legend>OpenSky OAuth2</legend><label>Client ID<input name=client_id type=text value='{html.escape(config.opensky.client_id)}'></label><label>Client Secret<input name=client_secret type=password placeholder='Leave blank to keep current secret'></label><label>Update interval (seconds)<input name=poll_interval type=number min=10 max=3600 value='{config.opensky.poll_interval_seconds}'></label></fieldset>
<fieldset><legend>Display</legend><label><input name=show_callsign type=checkbox{checked(config.ui.info_mode!='hidden')}> Callsign</label><label><input name=show_altitude type=checkbox{checked(config.ui.show_altitude)}> Altitude</label><label><input name=show_speed type=checkbox{checked(config.ui.show_speed)}> Speed</label><label><input name=show_scanline type=checkbox{checked(config.ui.show_scanline)}> Radar scanline</label><label><input name=show_heading type=checkbox{checked(config.ui.show_aircraft_heading)}> Aircraft heading symbol</label>{highlight_inputs}<small>Use the OpenSky/transponder callsign (often ICAO format, such as EVA123). Matching ignores case and spaces. Leave all fields blank to disable highlighting.</small><label>Rotation<select name=rotation><option value=90{selected(config.touch.rotation,90)}>90°</option><option value=270{selected(config.touch.rotation,270)}>270° (180° flipped)</option></select></label><small>Changing rotation updates the PiTFT boot overlay and automatically reboots the device.</small><label>Brightness: <output id=brightness_value>{config.display.brightness_percent}%</output><input name=brightness type=range min=10 max=100 step=5 value='{config.display.brightness_percent}' oninput='brightness_value.value=this.value+"%"'></label><small>Brightness uses PWM on GPIO 18. The 10% minimum prevents accidentally making the settings screen invisible.</small></fieldset>
<fieldset><legend>Localization</legend><label>Altitude unit<select name=altitude_unit><option value=m{selected(config.localization.altitude_unit,'m')}>m</option><option value=ft{selected(config.localization.altitude_unit,'ft')}>ft</option></select></label><label>Speed unit<select name=speed_unit><option value=kt{selected(config.localization.speed_unit,'kt')}>kt</option><option value=kmh{selected(config.localization.speed_unit,'kmh')}>km/h</option></select></label><label>Timezone<input name=timezone type=text value='{html.escape(config.localization.timezone)}'></label></fieldset>
<button type=submit>Save and restart radar</button></form>
<fieldset><legend>Wi-Fi configuration</legend><p>State: {html.escape(wifi_status.mode if wifi_status else 'UNKNOWN')} {html.escape(wifi_status.ssid if wifi_status else '')}</p><form method=post action=/wifi><input type=hidden name=csrf value='{token}'><label>Network<select name=ssid required>{wifi_options}</select></label><label>Password<input name=password type=password minlength=8 maxlength=63 required></label><button type=submit>Connect to Wi-Fi</button><p class=warn>The current connection will close. If connection fails, {html.escape(config.wifi.hotspot_ssid)} returns automatically.</p></form></fieldset></body></html>"""
            self._send(200, page, set_cookie=True)

        def do_POST(self) -> None:
            if not self._authorized():
                self._send(403, "<h1>403</h1>")
                return
            form = self._form()
            if not secrets.compare_digest(form.get("csrf", [""])[0], token):
                self._send(403, "<h1>Invalid request token</h1>")
                return
            try:
                if urllib.parse.urlparse(self.path).path == "/wifi":
                    ssid = form["ssid"][0]
                    password = form["password"][0]
                    if not 1 <= len(ssid) <= 32 or not 8 <= len(password) <= 63:
                        raise ValueError("SSID or password length is invalid")
                    if wifi_manager is None:
                        raise ValueError("Wi-Fi manager is unavailable")
                    wifi_manager.connect_async(ssid, password)
                    self._send(202, f"<h1>Wi-Fi connection started</h1><p>Connect your device to {html.escape(ssid)} and reopen the radar at its new IP address. If it fails, reconnect to {html.escape(config.wifi.hotspot_ssid)} and open http://{html.escape(config.wifi.gateway)}:{config.web.port}/.</p>")
                    return
                distance_unit = form["distance_unit"][0]
                radius = _checked_float(form, "radius", 1, 500)
                radius_km = radius if distance_unit == "km" else radius * 1.852
                timezone = form["timezone"][0]
                rotation = _checked_int(form, "rotation", 90, 270)
                if rotation not in {90, 270}:
                    raise ValueError("Rotation must be 90 or 270 degrees")
                if distance_unit not in {"km", "nm"} or form["altitude_unit"][0] not in {"m", "ft"} or form["speed_unit"][0] not in {"kt", "kmh"}:
                    raise ValueError("Invalid unit")
                if not timezone or ".." in timezone or len(timezone) > 64:
                    raise ValueError("Invalid timezone")
                timezone_result = subprocess.run(["timedatectl", "set-timezone", timezone], capture_output=True, timeout=10)
                if timezone_result.returncode != 0:
                    raise ValueError("The operating system rejected that timezone")
                opensky = {"client_id": form["client_id"][0], "poll_interval_seconds": _checked_int(form, "poll_interval", 10, 3600)}
                if form["client_secret"][0]:
                    opensky["client_secret"] = form["client_secret"][0]
                rotation_changed = rotation != config.touch.rotation
                if rotation_changed:
                    apply_display_rotation(rotation)
                try:
                    update_settings({
                        "display": {"brightness_percent": _checked_int(form, "brightness", 10, 100)},
                        "radar": {"latitude": _checked_float(form,"latitude",-90,90), "longitude": _checked_float(form,"longitude",-180,180), "radius_km": radius_km},
                        "opensky": opensky,
                        "ui": {"info_mode": "callsign" if "show_callsign" in form else "hidden", "show_altitude": "show_altitude" in form, "show_speed": "show_speed" in form, "show_scanline": "show_scanline" in form, "show_aircraft_heading": "show_heading" in form, "highlight_callsigns": _highlight_callsigns(form)},
                        "touch": {"rotation": rotation},
                        "localization": {"distance_unit": distance_unit, "altitude_unit": form["altitude_unit"][0], "speed_unit": form["speed_unit"][0], "timezone": timezone},
                    }, transactional=True)
                except (OSError, ValueError, TypeError):
                    if rotation_changed:
                        try:
                            apply_display_rotation(config.touch.rotation)
                        except (OSError, ValueError, subprocess.TimeoutExpired):
                            LOG.exception("failed to roll back display rotation")
                    raise
                if rotation_changed:
                    self._send(200, "<h1>Settings saved</h1><p>Display rotation changed. The device is rebooting now; reconnect in about one minute.</p>")
                    threading.Timer(0.5, request_reboot).start()
                else:
                    self._send(200, "<h1>Settings saved</h1><p>Radar service is restarting.</p>")
                    threading.Timer(0.5, request_restart).start()
            except (KeyError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
                self._send(400, f"<h1>Invalid setting</h1><p>{html.escape(str(error))}</p>")

    return Handler


class SettingsWebServer:
    def __init__(self, config: AppConfig, token: str, request_restart: Callable[[], None], wifi_manager: WifiManager | None = None) -> None:
        self.server = ThreadingHTTPServer(("0.0.0.0", config.web.port), build_handler(config, token, request_restart, wifi_manager))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="settings-web", daemon=True)

    def start(self) -> None:
        self.thread.start()
        LOG.info("settings web server listening on port %d", self.server.server_port)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
