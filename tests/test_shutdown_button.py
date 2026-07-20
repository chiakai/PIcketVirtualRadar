import unittest
from unittest.mock import patch

from picket_virtual_radar.system_health import HelpButton, ShutdownButton


class FakeGPIO:
    def __init__(self):
        self.pressed = True

    def gpio_read(self, handle, gpio):
        return 0 if self.pressed else 1


class ShutdownButtonTests(unittest.TestCase):
    def test_help_button_fires_once_when_released(self):
        gpio = FakeGPIO()
        button = HelpButton(gpio=27, debounce_seconds=0.05)
        button._backend = gpio
        button._handle = 1

        self.assertFalse(button.poll(1.0))
        self.assertFalse(button.poll(1.1))
        gpio.pressed = False
        self.assertTrue(button.poll(1.2))
        self.assertFalse(button.poll(1.3))

    def test_help_button_ignores_contact_bounce(self):
        gpio = FakeGPIO()
        button = HelpButton(gpio=27, debounce_seconds=0.05)
        button._backend = gpio
        button._handle = 1
        button.poll(1.0)
        gpio.pressed = False
        self.assertFalse(button.poll(1.01))

    def test_long_press_requests_systemd_poweroff(self):
        button = ShutdownButton(gpio=22, hold_seconds=3)
        button._backend = FakeGPIO()
        button._handle = 1

        self.assertFalse(button.poll(10))
        with patch("picket_virtual_radar.system_health.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertTrue(button.poll(13))
            run.assert_called_once_with(
                ["systemctl", "poweroff"],
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_failed_poweroff_returns_false(self):
        button = ShutdownButton(gpio=22, hold_seconds=3)
        button._backend = FakeGPIO()
        button._handle = 1
        button.poll(10)

        with patch("picket_virtual_radar.system_health.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "not authorized"
            run.return_value.stdout = ""
            self.assertFalse(button.poll(13))


if __name__ == "__main__":
    unittest.main()
