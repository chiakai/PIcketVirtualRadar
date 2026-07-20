import unittest

from picket_virtual_radar.app import RadarApplication
from picket_virtual_radar.config import AppConfig, WebConfig


class AppZoomTests(unittest.TestCase):
    def test_double_range_tap_only_changes_display_radius(self):
        app = RadarApplication(AppConfig(web=WebConfig(enabled=False)))
        api_radius = app.geometry.radius_km
        app._handle_range_tap(10.0)
        app._handle_range_tap(10.3)
        self.assertEqual(app.display_geometry.radius_km, api_radius / 2)
        self.assertEqual(app.geometry.radius_km, api_radius)

    def test_second_double_tap_restores_full_display_radius(self):
        app = RadarApplication(AppConfig(web=WebConfig(enabled=False)))
        app._handle_range_tap(10.0)
        app._handle_range_tap(10.2)
        app._handle_range_tap(11.0)
        app._handle_range_tap(11.2)
        self.assertEqual(app.display_geometry.radius_km, app.geometry.radius_km)
