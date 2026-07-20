import unittest

from picket_virtual_radar.backlight import BacklightController


class FakeGPIO:
    def __init__(self):
        self.calls = []

    def gpiochip_open(self, chip):
        self.calls.append(("open", chip))
        return 7

    def gpio_claim_output(self, handle, gpio, level):
        self.calls.append(("claim", handle, gpio, level))

    def tx_pwm(self, handle, gpio, frequency, duty):
        self.calls.append(("pwm", handle, gpio, frequency, duty))

    def gpio_write(self, handle, gpio, level):
        self.calls.append(("write", handle, gpio, level))

    def gpiochip_close(self, handle):
        self.calls.append(("close", handle))


class BacklightTests(unittest.TestCase):
    def test_applies_configured_pwm_and_releases_on_close(self):
        backend = FakeGPIO()
        controller = BacklightController(80)
        self.assertTrue(controller.open(backend))
        self.assertIn(("pwm", 7, 18, 1000, 80.0), backend.calls)
        controller.close()
        self.assertIn(("write", 7, 18, 1), backend.calls)
        self.assertIn(("close", 7), backend.calls)
