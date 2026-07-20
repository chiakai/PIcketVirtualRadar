from __future__ import annotations

import logging
from types import ModuleType


LOG = logging.getLogger(__name__)


class BacklightController:
    """Drive the Product 2423 backlight using software PWM on BCM GPIO 18."""

    def __init__(self, brightness_percent: int, gpio: int = 18, frequency: int = 1000) -> None:
        self.brightness_percent = brightness_percent
        self.gpio = gpio
        self.frequency = frequency
        self._backend: ModuleType | None = None
        self._handle: int | None = None

    def open(self, backend: ModuleType | None = None) -> bool:
        try:
            if backend is None:
                import lgpio as backend
            self._backend = backend
            self._handle = backend.gpiochip_open(0)
            backend.gpio_claim_output(self._handle, self.gpio, 1)
            backend.tx_pwm(
                self._handle,
                self.gpio,
                self.frequency,
                float(self.brightness_percent),
            )
            LOG.info(
                "PiTFT backlight ready: GPIO %d, %d Hz, %d%%",
                self.gpio,
                self.frequency,
                self.brightness_percent,
            )
            return True
        except (ImportError, OSError, RuntimeError) as error:
            LOG.warning("backlight PWM unavailable; leaving hardware default on: %s", error)
            self.close()
            return False

    def close(self) -> None:
        if self._backend is not None and self._handle is not None:
            try:
                self._backend.tx_pwm(self._handle, self.gpio, 0, 0)
                self._backend.gpio_write(self._handle, self.gpio, 1)
                self._backend.gpiochip_close(self._handle)
            except (OSError, RuntimeError):
                LOG.exception("failed to release backlight GPIO")
        self._handle = None
        self._backend = None
