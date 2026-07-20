import unittest

from picket_virtual_radar.app import RadarApplication
from picket_virtual_radar.radar_renderer import RadarRenderer
from picket_virtual_radar.touch import Gesture


class HelpOverlayTests(unittest.TestCase):
    def test_vertical_swipe_scrolls_and_clamps_help(self):
        app = RadarApplication.__new__(RadarApplication)
        app.overlay = "help"
        app.help_scroll = 0

        app._handle_gesture(Gesture("swipe", 100, 50, "up"), ())
        self.assertEqual(app.help_scroll, 5)
        for _ in range(20):
            app._handle_gesture(Gesture("swipe", 100, 50, "up"), ())
        self.assertEqual(app.help_scroll, RadarRenderer.help_scroll_limit())

        app._handle_gesture(Gesture("swipe", 100, 180, "down"), ())
        self.assertEqual(app.help_scroll, RadarRenderer.help_scroll_limit() - 5)

    def test_horizontal_swipe_does_nothing_in_help(self):
        app = RadarApplication.__new__(RadarApplication)
        app.overlay = "help"
        app.help_scroll = 5
        app._handle_gesture(Gesture("swipe", 40, 100, "left"), ())
        self.assertEqual(app.help_scroll, 5)


if __name__ == "__main__":
    unittest.main()
