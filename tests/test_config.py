import json
import tempfile
import unittest
from pathlib import Path

from picket_virtual_radar.config import AppConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self) -> None:
        self.assertEqual(load_config(Path("missing-config.json")), AppConfig())

    def test_loads_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"display": {"fps": 24}, "runtime": {"logic_hz": 8}}),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.display.fps, 24)
            self.assertEqual(config.runtime.logic_hz, 8)

    def test_rejects_invalid_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"display":{"fps":0}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_loads_radar_and_opensky(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({
                    "radar": {"latitude": 25.1, "longitude": 121.5, "radius_km": 30},
                    "opensky": {"client_id": "id", "client_secret": "secret", "poll_interval_seconds": 20},
                }),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.radar.radius_km, 30)
            self.assertEqual(config.opensky.client_id, "id")

    def test_loads_web_ui_and_units(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({
                    "ui": {"show_altitude": False, "show_speed": True},
                    "localization": {"distance_unit": "nm", "altitude_unit": "ft", "speed_unit": "kt", "timezone": "Asia/Taipei"},
                    "web": {"enabled": True, "port": 8081, "access_token": "token"},
                }),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertFalse(config.ui.show_altitude)
            self.assertEqual(config.localization.distance_unit, "nm")
            self.assertEqual(config.web.port, 8081)

    def test_normalizes_up_to_three_highlight_callsigns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"ui": {"highlight_callsigns": [" eva 123 ", "CAL456", "eva123"]}}),
                encoding="utf-8",
            )
            self.assertEqual(load_config(path).ui.highlight_callsigns, ("EVA123", "CAL456"))

    def test_rejects_more_than_three_highlight_callsigns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"ui": {"highlight_callsigns": ["A1", "A2", "A3", "A4"]}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "at most 3"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
