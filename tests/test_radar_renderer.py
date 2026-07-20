import unittest

from picket_virtual_radar.radar_renderer import HELP_LINES, HELP_VISIBLE_LINES, RadarRenderer, aircraft_is_highlighted


class RadarRendererTests(unittest.TestCase):
    def test_help_overlay_has_scrollable_content(self):
        self.assertGreater(len(HELP_LINES), HELP_VISIBLE_LINES)
        self.assertEqual(RadarRenderer.help_scroll_limit(), len(HELP_LINES) - HELP_VISIBLE_LINES)

    def test_callsign_match_ignores_case_and_spaces(self):
        self.assertTrue(aircraft_is_highlighted(" eva 123 ", {"EVA123"}))

    def test_empty_or_different_callsign_is_not_highlighted(self):
        self.assertFalse(aircraft_is_highlighted("", {"EVA123"}))
        self.assertFalse(aircraft_is_highlighted("CAL456", {"EVA123"}))


if __name__ == "__main__":
    unittest.main()
