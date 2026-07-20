import math
import unittest

from picket_virtual_radar.config import TrackingConfig
from picket_virtual_radar.geometry import EARTH_RADIUS_KM
from picket_virtual_radar.models import AircraftView
from picket_virtual_radar.tracking import AircraftTracker


def aircraft(**overrides):
    values = {
        "icao24": "ABC123",
        "callsign": "TEST1",
        "latitude": 25.0,
        "longitude": 121.0,
        "heading": 90.0,
        "altitude_m": 10000.0,
        "velocity_mps": 100.0,
        "vertical_rate_mps": 2.0,
        "on_ground": False,
        "last_contact_epoch": 990.0,
    }
    values.update(overrides)
    return AircraftView(**values)


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.config = TrackingConfig(interpolation_seconds=2, prediction_seconds=20, stale_after_seconds=90, show_on_ground=False)
        self.tracker = AircraftTracker(self.config, clock=lambda: 0, wall_clock=lambda: 1000)

    def test_icao24_is_unique_and_normalized(self):
        self.tracker.ingest([aircraft(), aircraft(callsign="NEW")], now=0)
        self.assertEqual(self.tracker.count, 1)
        self.assertEqual(self.tracker.views(now=0)[0].icao24, "abc123")
        self.assertEqual(self.tracker.views(now=0)[0].callsign, "NEW")

    def test_preserves_all_flight_fields(self):
        self.tracker.ingest([aircraft()], now=0)
        view = self.tracker.views(now=0)[0]
        self.assertEqual(view.altitude_m, 10000)
        self.assertEqual(view.velocity_mps, 100)
        self.assertEqual(view.heading, 90)
        self.assertEqual(view.vertical_rate_mps, 2)
        self.assertFalse(view.on_ground)

    def test_interpolates_from_current_to_new_position(self):
        self.tracker.ingest([aircraft(latitude=25.0)], now=0)
        self.tracker.ingest([aircraft(latitude=25.2, velocity_mps=None)], now=10)
        self.assertAlmostEqual(self.tracker.views(now=10)[0].latitude, 25.0)
        self.assertAlmostEqual(self.tracker.views(now=11)[0].latitude, 25.1)
        self.assertAlmostEqual(self.tracker.views(now=12)[0].latitude, 25.2)

    def test_predicts_position_from_speed_and_heading(self):
        self.tracker.ingest([aircraft()], now=0)
        view = self.tracker.views(now=12)[0]
        expected_delta = math.degrees(1.0 / (EARTH_RADIUS_KM * math.cos(math.radians(25))))
        self.assertAlmostEqual(view.longitude, 121.0 + expected_delta, places=5)
        self.assertTrue(view.predicted)

    def test_prediction_is_capped(self):
        self.tracker.ingest([aircraft()], now=0)
        at_limit = self.tracker.views(now=22)[0]
        much_later = self.tracker.views(now=50)[0]
        self.assertAlmostEqual(at_limit.longitude, much_later.longitude)

    def test_on_ground_aircraft_is_not_predicted(self):
        tracker = AircraftTracker(
            TrackingConfig(interpolation_seconds=2, prediction_seconds=20, stale_after_seconds=90, show_on_ground=True),
            clock=lambda: 0,
            wall_clock=lambda: 1000,
        )
        tracker.ingest([aircraft(on_ground=True)], now=0)
        view = tracker.views(now=15)[0]
        self.assertEqual(view.longitude, 121.0)
        self.assertFalse(view.predicted)

    def test_on_ground_aircraft_is_hidden_by_default(self):
        self.tracker.ingest([aircraft(on_ground=True)], now=0)
        self.assertEqual(self.tracker.count, 0)

    def test_on_ground_aircraft_can_be_enabled(self):
        tracker = AircraftTracker(
            TrackingConfig(show_on_ground=True), clock=lambda: 0, wall_clock=lambda: 1000
        )
        tracker.ingest([aircraft(on_ground=True)], now=0)
        self.assertEqual(tracker.count, 1)

    def test_stale_track_expires(self):
        self.tracker.ingest([aircraft()], now=0)
        self.assertEqual(len(self.tracker.views(now=90)), 1)
        self.assertEqual(len(self.tracker.views(now=91)), 0)

    def test_age_includes_source_age_and_elapsed_time(self):
        self.tracker.ingest([aircraft(last_contact_epoch=990)], now=0)
        self.assertEqual(self.tracker.views(now=5)[0].data_age_seconds, 15)


if __name__ == "__main__":
    unittest.main()
