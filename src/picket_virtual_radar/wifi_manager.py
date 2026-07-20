from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import WifiConfig


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class WifiStatus:
    mode: str = "CHECKING"
    ssid: str = ""
    ip: str = "--"
    message: str = ""
    signal_percent: int | None = None


def _split_terse(line: str) -> list[str]:
    values, current, escaped = [], [], False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            values.append("".join(current))
            current = []
        else:
            current.append(character)
    values.append("".join(current))
    return values


class WifiManager:
    def __init__(
        self,
        config: WifiConfig,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.runner = runner
        self.clock = clock
        self._status = WifiStatus()
        self._networks: tuple[tuple[str, int, str], ...] = ()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._requests: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._run, name="wifi-manager", daemon=True)
        self._disconnected_at = self.clock()
        self._ap_started_at: float | None = None
        self._signal_percent: int | None = None
        self._last_reconnect_attempt = 0.0
        self._gpio_backend = None
        self._gpio_handle = None
        self._button_down_at: float | None = None
        self._button_fired = False

    def _nmcli(self, *arguments: str, timeout: int = 20, secret_input: str | None = None) -> subprocess.CompletedProcess[str]:
        options = ["nmcli", "--wait", str(timeout)]
        if secret_input is not None:
            options.append("--ask")
        return self.runner(
            [*options, *arguments],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            input=None if secret_input is None else secret_input + "\n",
            env={**os.environ, "LC_ALL": "C"},
        )

    def start(self) -> None:
        if not self.config.fallback_enabled:
            return
        self._open_button()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        self._close_button()

    def status(self) -> WifiStatus:
        with self._lock:
            return self._status

    def networks(self) -> tuple[tuple[str, int, str], ...]:
        with self._lock:
            return self._networks

    def connect_async(self, ssid: str, password: str) -> None:
        while not self._requests.empty():
            try:
                self._requests.get_nowait()
            except queue.Empty:
                break
        self._requests.put_nowait((ssid, password))

    def _set_status(self, mode: str, ssid: str = "", ip: str = "--", message: str = "", signal_percent: int | None = None) -> None:
        with self._lock:
            self._status = WifiStatus(mode, ssid, ip, message, signal_percent)

    def _ethernet_status(self) -> tuple[bool, str]:
        try:
            if Path("/sys/class/net/eth0/carrier").read_text(encoding="utf-8").strip() != "1":
                return False, "--"
        except OSError:
            return False, "--"
        devices = self._nmcli("-t", "-e", "yes", "-f", "DEVICE,TYPE,STATE", "device", "status", timeout=5)
        network_manager_connected = any(
            len(fields := _split_terse(line)) >= 3
            and fields[0] == "eth0"
            and fields[1] == "ethernet"
            and fields[2] == "connected"
            for line in devices.stdout.splitlines()
        )
        if devices.returncode != 0 or not network_manager_connected:
            return False, "--"
        addresses = self.runner(
            ["ip", "-4", "-o", "address", "show", "dev", "eth0", "scope", "global"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "LC_ALL": "C"},
        )
        routes = self.runner(
            ["ip", "-4", "route", "show", "default", "dev", "eth0"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "LC_ALL": "C"},
        )
        if addresses.returncode != 0 or routes.returncode != 0 or not addresses.stdout.strip() or not routes.stdout.strip():
            return False, "--"
        for field in addresses.stdout.split():
            if field.count(".") == 3 and "/" in field:
                return True, field.split("/", 1)[0]
        return False, "--"

    def _device(self) -> tuple[str, str, str]:
        result = self._nmcli("-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", self.config.interface)
        state, connection, ip = "", "", "--"
        for line in result.stdout.splitlines():
            key, _, value = line.partition(":")
            if key == "GENERAL.STATE":
                state = value
            elif key == "GENERAL.CONNECTION":
                connection = value
            elif key == "IP4.ADDRESS[1]":
                ip = value.split("/")[0]
        return state, connection, ip

    def _refresh(self) -> None:
        ethernet_active, ethernet_ip = self._ethernet_status()
        if ethernet_active:
            self._set_status("ETHERNET", ip=ethernet_ip, message="Ethernet connected")
            self._disconnected_at = self.clock()
            self._ap_started_at = None
            return
        state, connection, ip = self._device()
        if "100 (connected)" in state and connection == self.config.hotspot_ssid:
            self._set_status("AP", self.config.hotspot_ssid, self.config.gateway, "setup hotspot active")
            self._ap_started_at = self._ap_started_at or self.clock()
        elif "100 (connected)" in state:
            self._set_status("CLIENT", connection, ip, "connected", self._signal_percent)
            self._disconnected_at = self.clock()
            self._ap_started_at = None
        else:
            self._set_status("DISCONNECTED", message="waiting for known Wi-Fi")

    def _scan(self) -> None:
        result = self._nmcli("-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", self.config.interface, "--rescan", "auto")
        strongest: dict[str, tuple[int, str]] = {}
        active_signal = None
        for line in result.stdout.splitlines():
            fields = _split_terse(line)
            if len(fields) < 4 or not fields[1]:
                continue
            try:
                signal = int(fields[2])
            except ValueError:
                continue
            if fields[0] == "*":
                active_signal = signal
            if fields[1] not in strongest or signal > strongest[fields[1]][0]:
                strongest[fields[1]] = (signal, fields[3])
        self._signal_percent = active_signal
        networks = tuple(sorted(((ssid, signal, security) for ssid, (signal, security) in strongest.items()), key=lambda item: item[1], reverse=True))
        with self._lock:
            self._networks = networks

    def _start_hotspot(self) -> None:
        LOG.warning("starting Wi-Fi setup hotspot %s", self.config.hotspot_ssid)
        self._nmcli("connection", "delete", self.config.hotspot_ssid, timeout=10)
        result = self._nmcli(
            "device", "wifi", "hotspot", "ifname", self.config.interface,
            "con-name", self.config.hotspot_ssid, "ssid", self.config.hotspot_ssid,
            "password", self.config.hotspot_password,
            timeout=30,
        )
        if result.returncode == 0:
            self._nmcli("connection", "modify", self.config.hotspot_ssid, "ipv4.method", "shared", "ipv4.addresses", f"{self.config.gateway}/24", "connection.autoconnect", "no")
            self._nmcli("connection", "up", self.config.hotspot_ssid, timeout=30)
            self._ap_started_at = self.clock()
            self._set_status("AP", self.config.hotspot_ssid, self.config.gateway, "setup hotspot active")
        else:
            LOG.error("failed to start setup hotspot: %s", result.stderr.strip())

    def _connect(self, ssid: str, password: str) -> None:
        self._set_status("CONNECTING", ssid, message="trying new Wi-Fi")
        LOG.info("connecting to requested Wi-Fi SSID %s", ssid)
        self._nmcli("connection", "down", self.config.hotspot_ssid, timeout=10)
        result = self._nmcli(
            "device", "wifi", "connect", ssid,
            "ifname", self.config.interface, "name", f"PVR-{ssid}",
            timeout=self.config.connection_timeout_seconds,
            secret_input=password,
        )
        if result.returncode != 0:
            LOG.warning("new Wi-Fi connection failed; restoring setup hotspot")
            self._start_hotspot()
        else:
            self._refresh()

    def _try_known_connections(self) -> bool:
        result = self._nmcli("-t", "-e", "yes", "-f", "NAME,TYPE", "connection", "show")
        for line in result.stdout.splitlines():
            fields = _split_terse(line)
            if len(fields) < 2 or fields[1] != "802-11-wireless" or fields[0] == self.config.hotspot_ssid:
                continue
            attempt = self._nmcli("connection", "up", fields[0], "ifname", self.config.interface, timeout=self.config.connection_timeout_seconds)
            if attempt.returncode == 0:
                self._refresh()
                return self.status().mode == "CLIENT"
        return False

    def _reset_wifi(self) -> None:
        LOG.warning("physical Wi-Fi reset requested")
        result = self._nmcli("-t", "-f", "NAME,TYPE", "connection", "show")
        for line in result.stdout.splitlines():
            fields = _split_terse(line)
            if len(fields) >= 2 and fields[1] == "802-11-wireless" and fields[0] != self.config.hotspot_ssid:
                self._nmcli("connection", "delete", fields[0], timeout=10)
        self._start_hotspot()

    def _open_button(self) -> None:
        try:
            import lgpio
            self._gpio_backend = lgpio
            self._gpio_handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_input(self._gpio_handle, self.config.reset_button_gpio, lgpio.SET_PULL_UP)
        except (ImportError, OSError, RuntimeError) as error:
            LOG.warning("Wi-Fi reset button unavailable: %s", error)
            self._close_button()

    def _close_button(self) -> None:
        if self._gpio_backend is not None and self._gpio_handle is not None:
            try:
                self._gpio_backend.gpiochip_close(self._gpio_handle)
            except (OSError, RuntimeError):
                pass
        self._gpio_backend = self._gpio_handle = None

    def _poll_button(self) -> None:
        if self._gpio_backend is None or self._gpio_handle is None:
            return
        pressed = self._gpio_backend.gpio_read(self._gpio_handle, self.config.reset_button_gpio) == 0
        now = self.clock()
        if pressed and self._button_down_at is None:
            self._button_down_at, self._button_fired = now, False
        elif pressed and not self._button_fired and now - (self._button_down_at or now) >= self.config.reset_hold_seconds:
            self._button_fired = True
            self._reset_wifi()
        elif not pressed:
            self._button_down_at, self._button_fired = None, False

    def _run(self) -> None:
        last_scan = 0.0
        while not self._stop.is_set():
            try:
                try:
                    ssid, password = self._requests.get_nowait()
                except queue.Empty:
                    ssid = password = ""
                if ssid:
                    self._connect(ssid, password)
                self._refresh()
                now = self.clock()
                if now - last_scan >= 30:
                    self._scan()
                    last_scan = now
                status = self.status()
                if status.mode == "DISCONNECTED":
                    disconnected_for = now - self._disconnected_at
                    if disconnected_for >= 15 and now - self._last_reconnect_attempt >= 15:
                        self._last_reconnect_attempt = now
                        self._nmcli("device", "connect", self.config.interface, timeout=15)
                        self._refresh()
                    if self.status().mode == "DISCONNECTED" and disconnected_for >= self.config.fallback_after_seconds:
                        self._start_hotspot()
                elif status.mode == "AP" and self._ap_started_at is not None and now - self._ap_started_at >= self.config.hotspot_timeout_seconds:
                    self._nmcli("connection", "down", self.config.hotspot_ssid, timeout=10)
                    if not self._try_known_connections():
                        self._start_hotspot()
                    self._ap_started_at = None
                self._poll_button()
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                LOG.exception("Wi-Fi manager cycle failed")
            self._stop.wait(2)
