from __future__ import annotations

import errno
import logging
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from .config import TouchConfig


LOG = logging.getLogger(__name__)
EV_SYN = 0
EV_KEY = 1
EV_ABS = 3
ABS_X = 0
ABS_Y = 1
BTN_TOUCH = 330
SYN_REPORT = 0
INPUT_EVENT = struct.Struct("llHHI")


@dataclass(frozen=True)
class Gesture:
    kind: str
    x: int
    y: int
    direction: str | None = None


class GestureRecognizer:
    def __init__(self, config: TouchConfig) -> None:
        self.config = config
        self._down_position: tuple[int, int] | None = None
        self._last_position = (0, 0)
        self._down_at = 0.0

    def press(self, x: int, y: int, timestamp: float) -> None:
        self._down_position = (x, y)
        self._last_position = (x, y)
        self._down_at = timestamp

    def move(self, x: int, y: int) -> None:
        self._last_position = (x, y)

    def release(self, x: int, y: int, timestamp: float) -> Gesture | None:
        if self._down_position is None:
            return None
        start_x, start_y = self._down_position
        self._down_position = None
        delta_x = x - start_x
        delta_y = y - start_y
        distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5
        duration = timestamp - self._down_at
        if abs(delta_x) >= self.config.swipe_min_px and abs(delta_x) > abs(delta_y) * 1.3:
            return Gesture("swipe", x, y, "left" if delta_x < 0 else "right")
        if abs(delta_y) >= self.config.swipe_min_px and abs(delta_y) > abs(delta_x) * 1.3:
            return Gesture("swipe", x, y, "up" if delta_y < 0 else "down")
        if duration >= self.config.long_press_seconds and distance <= self.config.move_tolerance_px:
            return Gesture("long_press", x, y)
        if duration <= self.config.tap_max_seconds and distance <= self.config.move_tolerance_px:
            return Gesture("tap", x, y)
        return None


def transform_coordinates(raw_x: int, raw_y: int, width: int, height: int, rotation: int) -> tuple[int, int]:
    if rotation == 270:
        return max(0, min(width - 1, width - 1 - raw_y)), max(0, min(height - 1, raw_x))
    return max(0, min(width - 1, raw_y)), max(0, min(height - 1, height - 1 - raw_x))


def find_touch_device(device_name: str) -> Path | None:
    for name_path in sorted(Path("/sys/class/input").glob("event*/device/name")):
        try:
            if device_name in name_path.read_text(encoding="utf-8").strip():
                return Path("/dev/input") / name_path.parents[1].name
        except OSError:
            continue
    return None


class TouchInput:
    def __init__(self, config: TouchConfig, width: int, height: int, clock=time.monotonic) -> None:
        self.config = config
        self.width = width
        self.height = height
        self.clock = clock
        self.recognizer = GestureRecognizer(config)
        self._fd: int | None = None
        self._buffer = bytearray()
        self._raw_x = 0
        self._raw_y = 0
        self._pending_press = False
        self._active = False

    def open(self) -> bool:
        path = find_touch_device(self.config.device_name)
        if path is None:
            LOG.warning("touch device not found: %s", self.config.device_name)
            return False
        self._fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        LOG.info("touch input ready: %s (%s)", self.config.device_name, path)
        return True

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def poll(self) -> list[Gesture]:
        if self._fd is None:
            return []
        while True:
            try:
                chunk = os.read(self._fd, INPUT_EVENT.size * 32)
                if not chunk:
                    break
                self._buffer.extend(chunk)
            except OSError as error:
                if error.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                    break
                raise
        gestures = []
        while len(self._buffer) >= INPUT_EVENT.size:
            raw = self._buffer[: INPUT_EVENT.size]
            del self._buffer[: INPUT_EVENT.size]
            _seconds, _microseconds, event_type, code, value = INPUT_EVENT.unpack(raw)
            if event_type == EV_ABS and code == ABS_X:
                self._raw_x = value
            elif event_type == EV_ABS and code == ABS_Y:
                self._raw_y = value
            elif event_type == EV_KEY and code == BTN_TOUCH:
                x, y = transform_coordinates(self._raw_x, self._raw_y, self.width, self.height, self.config.rotation)
                now = self.clock()
                if value:
                    self._pending_press = True
                else:
                    gesture = self.recognizer.release(x, y, now)
                    self._active = False
                    if gesture is not None:
                        gestures.append(gesture)
            elif event_type == EV_SYN and code == SYN_REPORT:
                x, y = transform_coordinates(self._raw_x, self._raw_y, self.width, self.height, self.config.rotation)
                if self._pending_press:
                    self.recognizer.press(x, y, self.clock())
                    self._pending_press = False
                    self._active = True
                elif self._active:
                    self.recognizer.move(x, y)
        return gestures
