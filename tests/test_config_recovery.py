import json
import tempfile
import unittest
from pathlib import Path

from picket_virtual_radar.config_recovery import confirm_start, prepare_start
from picket_virtual_radar.settings_store import recovery_paths, update_settings


class ConfigRecoveryTests(unittest.TestCase):
    def test_transaction_is_confirmed_after_healthy_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"display":{"brightness_percent":80}}', encoding="utf-8")
            update_settings({"display": {"brightness_percent": 40}}, path, transactional=True)
            backup, pending = recovery_paths(path)
            self.assertTrue(backup.exists())
            self.assertTrue(pending.exists())
            self.assertFalse(prepare_start(path))
            self.assertTrue(confirm_start(path))
            self.assertFalse(pending.exists())
            self.assertEqual(json.loads(path.read_text())["display"]["brightness_percent"], 40)

    def test_third_failed_start_restores_last_known_good(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"display":{"brightness_percent":80}}', encoding="utf-8")
            update_settings({"display": {"brightness_percent": 20}}, path, transactional=True)
            self.assertFalse(prepare_start(path))
            self.assertFalse(prepare_start(path))
            self.assertTrue(prepare_start(path))
            self.assertEqual(json.loads(path.read_text())["display"]["brightness_percent"], 80)
            self.assertFalse(recovery_paths(path)[1].exists())

    def test_invalid_candidate_never_replaces_current_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"display":{"brightness_percent":80}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                update_settings({"display": {"brightness_percent": 0}}, path, transactional=True)
            self.assertEqual(json.loads(path.read_text())["display"]["brightness_percent"], 80)
