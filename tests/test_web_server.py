import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from picket_virtual_radar.config import AppConfig
from picket_virtual_radar.web_server import _highlight_callsigns, apply_display_rotation, ensure_access_token


class WebServerTests(unittest.TestCase):
    def test_highlight_callsigns_are_normalized_and_deduplicated(self):
        form = {
            "highlight_callsign_1": [" eva 123 "],
            "highlight_callsign_2": ["EVA123"],
            "highlight_callsign_3": ["cal456"],
        }
        self.assertEqual(_highlight_callsigns(form), ["EVA123", "CAL456"])

    def test_invalid_highlight_callsign_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ASCII"):
            _highlight_callsigns({"highlight_callsign_1": ["EVA/123"]})

    def test_rotation_helper_only_accepts_supported_angles(self):
        with self.assertRaisesRegex(ValueError, "90 or 270"):
            apply_display_rotation(180)

    @patch("picket_virtual_radar.web_server.subprocess.run")
    def test_rotation_uses_restricted_systemd_unit(self, run):
        run.return_value.returncode = 0
        apply_display_rotation(270)
        run.assert_called_once_with(
            ["systemctl", "start", "--wait", "picket-display-rotate@270.service"],
            capture_output=True,
            text=True,
            timeout=20,
        )

    @patch("picket_virtual_radar.web_server.subprocess.run")
    def test_rotation_helper_failure_is_reported(self, run):
        run.return_value.returncode = 1
        run.return_value.stderr = "not authorized"
        run.return_value.stdout = ""
        with self.assertRaisesRegex(ValueError, "not authorized"):
            apply_display_rotation(90)

    def test_generated_token_is_persisted_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"opensky": {"client_secret": "keep"}}), encoding="utf-8")
            previous = os.environ.get("PVR_CONFIG")
            os.environ["PVR_CONFIG"] = str(path)
            try:
                token = ensure_access_token(AppConfig())
            finally:
                if previous is None:
                    os.environ.pop("PVR_CONFIG", None)
                else:
                    os.environ["PVR_CONFIG"] = previous
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(token), 12)
            self.assertEqual(saved["web"]["access_token"], token)
            self.assertEqual(saved["opensky"]["client_secret"], "keep")


if __name__ == "__main__":
    unittest.main()
