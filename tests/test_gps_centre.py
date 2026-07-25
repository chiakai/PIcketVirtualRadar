import unittest
from types import SimpleNamespace

from picket_virtual_radar.app import RadarApplication
from picket_virtual_radar.config import AppConfig, GpsConfig
from picket_virtual_radar.geometry import RadarGeometry
from picket_virtual_radar.gps import GpsSnapshot


class FakeGpsReader:
    def __init__(self, snapshot):
        self.value = snapshot

    def snapshot(self):
        return self.value


class FakeDataLayer:
    def __init__(self):
        self.geometry = None

    def set_geometry(self, geometry):
        self.geometry = geometry


class GpsCentreTests(unittest.TestCase):
    def application(self, snapshot):
        app = RadarApplication.__new__(RadarApplication)
        app.config = AppConfig(gps=GpsConfig(enabled=True))
        app.geometry = RadarGeometry(
            latitude=app.config.radar.latitude,
            longitude=app.config.radar.longitude,
            radius_km=app.config.radar.radius_km,
        )
        app.display_geometry = app.geometry
        app.display_zoom = 1.0
        app.centre_source = "GPS WAIT"
        app.system_info = {}
        app.gps_reader = FakeGpsReader(snapshot)
        app.data_layer = FakeDataLayer()
        app.renderer = SimpleNamespace()
        return app

    def test_fix_updates_display_and_opensky_geometry(self):
        app = self.application(GpsSnapshot(25.2, 121.3, "FIX", "/dev/ttyUSB0", 1.0))
        app._update_gps_centre()
        self.assertEqual(app.centre_source, "GPS")
        self.assertAlmostEqual(app.geometry.latitude, 25.2)
        self.assertIs(app.data_layer.geometry, app.geometry)
        self.assertIsNone(app.renderer)
        self.assertEqual(app.system_info["centre_source"], "GPS")

    def test_waiting_for_fix_uses_configured_centre(self):
        app = self.application(GpsSnapshot(status="WAIT", device="/dev/ttyACM0"))
        app.geometry = RadarGeometry(latitude=25.2, longitude=121.3, radius_km=50)
        app.centre_source = "GPS"
        app._update_gps_centre()
        self.assertEqual(app.centre_source, "GPS WAIT")
        self.assertAlmostEqual(app.geometry.latitude, app.config.radar.latitude)
        self.assertEqual(app.system_info["gps_status"], "WAIT")


if __name__ == "__main__":
    unittest.main()
