import json
import tempfile
import unittest
from pathlib import Path

from picket_virtual_radar.settings_store import update_settings


class SettingsStoreTests(unittest.TestCase):
    def test_update_preserves_secret_and_other_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"opensky": {"client_secret": "keep-me"}, "ui": {"info_mode": "callsign"}}),
                encoding="utf-8",
            )
            update_settings({"ui": {"show_scanline": False}}, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["opensky"]["client_secret"], "keep-me")
            self.assertEqual(saved["ui"]["info_mode"], "callsign")
            self.assertFalse(saved["ui"]["show_scanline"])


if __name__ == "__main__":
    unittest.main()
