from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import GpsConfig


LOG = logging.getLogger(__name__)
AUTO_DEVICES = ("/dev/ttyUSB0", "/dev/ttyACM0")


@dataclass(frozen=True)
class GpsSnapshot:
    latitude: float | None = None
    longitude: float | None = None
    status: str = "DISABLED"
    device: str = "--"
    last_fix_monotonic: float | None = None


def _coordinate(value: str, hemisphere: str, degree_digits: int) -> float | None:
    if not value or len(value) <= degree_digits:
        return None
    try:
        degrees = float(value[:degree_digits])
        minutes = float(value[degree_digits:])
    except ValueError:
        return None
    if minutes >= 60:
        return None
    result = degrees + minutes / 60.0
    if hemisphere in {"S", "W"}:
        result = -result
    elif hemisphere not in {"N", "E"}:
        return None
    return result


def parse_nmea_position(sentence: str) -> tuple[float, float] | None:
    sentence = sentence.strip()
    if not sentence.startswith("$"):
        return None
    payload, separator, checksum = sentence[1:].partition("*")
    if separator:
        try:
            expected = int(checksum[:2], 16)
        except ValueError:
            return None
        actual = 0
        for character in payload:
            actual ^= ord(character)
        if actual != expected:
            return None
    fields = payload.split(",")
    message_type = fields[0][-3:] if fields else ""
    if message_type == "GGA" and len(fields) >= 7:
        if not fields[6].isdigit() or int(fields[6]) <= 0:
            return None
        latitude = _coordinate(fields[2], fields[3], 2)
        longitude = _coordinate(fields[4], fields[5], 3)
    elif message_type == "RMC" and len(fields) >= 7:
        if fields[2] != "A":
            return None
        latitude = _coordinate(fields[3], fields[4], 2)
        longitude = _coordinate(fields[5], fields[6], 3)
    else:
        return None
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


class UsbGpsReader:
    def __init__(self, config: GpsConfig, clock=time.monotonic) -> None:
        self.config = config
        self.clock = clock
        self._lock = threading.Lock()
        self._snapshot = GpsSnapshot(status="WAIT" if config.enabled else "DISABLED")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.enabled:
            return
        self._thread = threading.Thread(target=self._run, name="usb-gps", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def snapshot(self) -> GpsSnapshot:
        with self._lock:
            snapshot = self._snapshot
        if snapshot.last_fix_monotonic is not None and self.clock() - snapshot.last_fix_monotonic > self.config.fix_timeout_seconds:
            return GpsSnapshot(status="WAIT", device=snapshot.device)
        return snapshot

    def _devices(self) -> tuple[str, ...]:
        if self.config.device_path != "auto":
            return (self.config.device_path,)
        return tuple(path for path in AUTO_DEVICES if Path(path).exists())

    def _set_status(self, status: str, device: str = "--", position: tuple[float, float] | None = None) -> None:
        with self._lock:
            if position is None:
                previous = self._snapshot
                self._snapshot = GpsSnapshot(previous.latitude, previous.longitude, status, device, previous.last_fix_monotonic)
            else:
                self._snapshot = GpsSnapshot(position[0], position[1], "FIX", device, self.clock())

    def _open(self, device: str) -> int:
        descriptor = os.open(device, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
        try:
            import termios

            speed = getattr(termios, f"B{self.config.baud_rate}", termios.B9600)
            attributes = termios.tcgetattr(descriptor)
            attributes[0] = 0
            attributes[1] = 0
            attributes[2] = termios.CS8 | termios.CLOCAL | termios.CREAD
            attributes[3] = 0
            attributes[4] = speed
            attributes[5] = speed
            termios.tcsetattr(descriptor, termios.TCSANOW, attributes)
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    def _read_device(self, device: str) -> None:
        descriptor = self._open(device)
        LOG.info("USB GPS input ready: %s at %d baud", device, self.config.baud_rate)
        self._set_status("WAIT", device)
        buffer = bytearray()
        try:
            while not self._stop.wait(0.1):
                try:
                    chunk = os.read(descriptor, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    continue
                buffer.extend(chunk)
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    position = parse_nmea_position(raw.decode("ascii", errors="ignore"))
                    if position is not None:
                        self._set_status("FIX", device, position)
        finally:
            os.close(descriptor)

    def _run(self) -> None:
        while not self._stop.is_set():
            devices = self._devices()
            if not devices:
                self._set_status("NO DEVICE")
            for device in devices:
                if self._stop.is_set():
                    break
                try:
                    self._read_device(device)
                except OSError as error:
                    self._set_status("ERROR", device)
                    LOG.warning("USB GPS unavailable on %s: %s", device, error)
            self._stop.wait(3)
