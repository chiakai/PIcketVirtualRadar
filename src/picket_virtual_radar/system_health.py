from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthStatus:
    temperature_c: float | None = None
    undervoltage_now: bool = False
    undervoltage_occurred: bool = False
    throttled_now: bool = False
    throttled_occurred: bool = False

    @property
    def warning(self) -> str:
        if self.undervoltage_now:
            return "LOW VOLTAGE"
        if self.temperature_c is not None and self.temperature_c >= 80:
            return "OVERHEAT"
        if self.throttled_now:
            return "THROTTLED"
        if self.undervoltage_occurred or self.throttled_occurred:
            return "POWER HISTORY"
        return ""


class HealthMonitor:
    def __init__(self, interval_seconds: float = 5.0) -> None:
        self.interval_seconds = interval_seconds
        self._last_read = 0.0
        self._status = HealthStatus()

    def status(self) -> HealthStatus:
        now = time.monotonic()
        if now - self._last_read < self.interval_seconds:
            return self._status
        self._last_read = now
        temperature = None
        try:
            temperature = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
        except (OSError, ValueError):
            pass
        throttled = 0
        try:
            result = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2)
            throttled = int(result.stdout.strip().split("=", 1)[1], 16) if result.returncode == 0 else 0
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass
        self._status = HealthStatus(
            temperature_c=temperature,
            undervoltage_now=bool(throttled & (1 << 0)),
            throttled_now=bool(throttled & (1 << 2)),
            undervoltage_occurred=bool(throttled & (1 << 16)),
            throttled_occurred=bool(throttled & (1 << 18)),
        )
        return self._status


class SystemdNotifier:
    def __init__(self) -> None:
        self.address = os.environ.get("NOTIFY_SOCKET", "")
        watchdog_usec = int(os.environ.get("WATCHDOG_USEC", "0") or 0)
        self.watchdog_interval = watchdog_usec / 2_000_000 if watchdog_usec else 0.0
        self._last_watchdog = 0.0

    def notify(self, message: str) -> bool:
        if not self.address:
            return False
        address = "\0" + self.address[1:] if self.address.startswith("@") else self.address
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
                client.connect(address)
                client.sendall(message.encode("utf-8"))
            return True
        except OSError:
            LOG.exception("systemd notification failed")
            return False

    def ready(self) -> None:
        self.notify("READY=1\nSTATUS=Radar display and Web UI ready")

    def watchdog(self, now: float) -> None:
        if self.watchdog_interval and now - self._last_watchdog >= self.watchdog_interval:
            self.notify("WATCHDOG=1")
            self._last_watchdog = now

    def stopping(self) -> None:
        self.notify("STOPPING=1\nSTATUS=Stopping cleanly")


class ShutdownButton:
    def __init__(self, gpio: int = 22, hold_seconds: float = 3.0) -> None:
        self.gpio = gpio
        self.hold_seconds = hold_seconds
        self._backend = None
        self._handle = None
        self._down_at: float | None = None
        self._fired = False

    def open(self) -> bool:
        try:
            import lgpio
            self._backend = lgpio
            self._handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_input(self._handle, self.gpio, lgpio.SET_PULL_UP)
            return True
        except (ImportError, OSError, RuntimeError) as error:
            LOG.warning("safe-shutdown button unavailable: %s", error)
            self.close()
            return False

    def poll(self, now: float) -> bool:
        if self._backend is None or self._handle is None:
            return False
        pressed = self._backend.gpio_read(self._handle, self.gpio) == 0
        if pressed and self._down_at is None:
            self._down_at, self._fired = now, False
        elif pressed and not self._fired and now - (self._down_at or now) >= self.hold_seconds:
            self._fired = True
            LOG.warning("physical safe shutdown requested on GPIO %d", self.gpio)
            try:
                result = subprocess.run(
                    ["systemctl", "poweroff"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    LOG.error(
                        "safe shutdown command failed with exit code %d: %s",
                        result.returncode,
                        (result.stderr or result.stdout).strip() or "no error output",
                    )
                    return False
                return True
            except (OSError, subprocess.TimeoutExpired):
                LOG.exception("safe shutdown request failed")
        elif not pressed:
            self._down_at, self._fired = None, False
        return False

    def close(self) -> None:
        if self._backend is not None and self._handle is not None:
            try:
                self._backend.gpiochip_close(self._handle)
            except (OSError, RuntimeError):
                pass
        self._backend = self._handle = None


class HelpButton:
    def __init__(self, gpio: int = 27, debounce_seconds: float = 0.05) -> None:
        self.gpio = gpio
        self.debounce_seconds = debounce_seconds
        self._backend = None
        self._handle = None
        self._down_at: float | None = None

    def open(self) -> bool:
        try:
            import lgpio
            self._backend = lgpio
            self._handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_input(self._handle, self.gpio, lgpio.SET_PULL_UP)
            return True
        except (ImportError, OSError, RuntimeError) as error:
            LOG.warning("help button unavailable: %s", error)
            self.close()
            return False

    def poll(self, now: float) -> bool:
        if self._backend is None or self._handle is None:
            return False
        pressed = self._backend.gpio_read(self._handle, self.gpio) == 0
        if pressed and self._down_at is None:
            self._down_at = now
        elif not pressed and self._down_at is not None:
            duration = now - self._down_at
            self._down_at = None
            if duration >= self.debounce_seconds:
                LOG.info("physical help button pressed on GPIO %d", self.gpio)
                return True
        return False

    def close(self) -> None:
        if self._backend is not None and self._handle is not None:
            try:
                self._backend.gpiochip_close(self._handle)
            except (OSError, RuntimeError):
                pass
        self._backend = self._handle = None
