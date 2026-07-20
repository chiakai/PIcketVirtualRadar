import math
import unittest

from picket_virtual_radar.geometry import EARTH_RADIUS_KM, RadarGeometry


class RadarGeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.geometry = RadarGeometry(latitude=60.0, longitude=10.0, radius_km=50.0)

    def test_centre_maps_to_centre_pixel(self) -> None:
        self.assertEqual(self.geometry.to_screen(60.0, 10.0), (120.0, 120.0))

    def test_north_maps_up(self) -> None:
        latitude = 60.0 + math.degrees(10.0 / EARTH_RADIUS_KM)
        x, y = self.geometry.to_screen(latitude, 10.0)
        self.assertAlmostEqual(x, 120.0, places=5)
        self.assertAlmostEqual(y, 97.6, places=1)

    def test_longitude_is_corrected_by_latitude(self) -> None:
        longitude = 10.0 + math.degrees(10.0 / (EARTH_RADIUS_KM * math.cos(math.radians(60.0))))
        x, y = self.geometry.to_screen(60.0, longitude)
        self.assertAlmostEqual(x, 142.4, places=1)
        self.assertAlmostEqual(y, 120.0, places=5)

    def test_outside_radius_is_rejected(self) -> None:
        latitude = 60.0 + math.degrees(51.0 / EARTH_RADIUS_KM)
        self.assertFalse(self.geometry.contains(latitude, 10.0))


if __name__ == "__main__":
    unittest.main()
