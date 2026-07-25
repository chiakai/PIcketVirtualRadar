import unittest

from picket_virtual_radar.config import GpsConfig
from picket_virtual_radar.gps import UsbGpsReader, parse_nmea_position


class GpsTests(unittest.TestCase):
    def test_parses_valid_gga_fix(self):
        position = parse_nmea_position(
            "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
        )
        self.assertAlmostEqual(position[0], 48.1173, places=4)
        self.assertAlmostEqual(position[1], 11.5166667, places=4)

    def test_parses_valid_rmc_fix(self):
        position = parse_nmea_position(
            "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
        )
        self.assertAlmostEqual(position[0], 48.1173, places=4)
        self.assertAlmostEqual(position[1], 11.5166667, places=4)

    def test_rejects_no_fix_and_bad_checksum(self):
        self.assertIsNone(parse_nmea_position("$GPGGA,123519,,,,,0,00,99.9,,,,,,*48"))
        self.assertIsNone(parse_nmea_position("$GPGGA,123519,4807.038,N,01131.000,E,1,08*00"))

    def test_stale_fix_returns_wait_status(self):
        now = [10.0]
        reader = UsbGpsReader(GpsConfig(enabled=True, fix_timeout_seconds=5), clock=lambda: now[0])
        reader._set_status("FIX", "/dev/ttyUSB0", (25.1, 121.2))
        self.assertEqual(reader.snapshot().status, "FIX")
        now[0] = 16.0
        stale = reader.snapshot()
        self.assertEqual(stale.status, "WAIT")
        self.assertIsNone(stale.latitude)


if __name__ == "__main__":
    unittest.main()
