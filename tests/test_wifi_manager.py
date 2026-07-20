import subprocess
import unittest
from unittest.mock import patch

from picket_virtual_radar.config import WifiConfig
from picket_virtual_radar.wifi_manager import WifiManager, _split_terse


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        stdout, returncode = self.outputs.pop(0)
        return subprocess.CompletedProcess(command, returncode, stdout, "failed" if returncode else "")


class WifiManagerTests(unittest.TestCase):
    def test_terse_parser_handles_escaped_colons(self):
        self.assertEqual(_split_terse(r"Cafe\:Guest:77:WPA2"), ["Cafe:Guest", "77", "WPA2"])

    def test_connected_client_status(self):
        runner = FakeRunner([(
            "GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Iceland\nIP4.ADDRESS[1]:192.168.66.202/24\n",
            0,
        )])
        manager = WifiManager(WifiConfig(), runner=runner)
        manager._refresh()
        self.assertEqual(manager.status().mode, "CLIENT")
        self.assertEqual(manager.status().ip, "192.168.66.202")

    def test_failed_requested_connection_restores_hotspot(self):
        runner = FakeRunner([
            ("", 0),
            ("", 10),
            ("", 0),
            ("success", 0),
            ("", 0),
            ("", 0),
        ])
        manager = WifiManager(WifiConfig(), runner=runner)
        manager._connect("BadNetwork", "wrongpass")
        self.assertEqual(manager.status().mode, "AP")
        flattened = [" ".join(call) for call in runner.calls]
        self.assertTrue(any("hotspot" in call for call in flattened))
        connect_command = next(call for call in runner.calls if "connect" in call)
        self.assertIn("--ask", connect_command)
        self.assertNotIn("wrongpass", connect_command)

    def test_ethernet_status_takes_priority_and_exposes_its_ip(self):
        manager = WifiManager(WifiConfig(), runner=FakeRunner([]))
        with patch.object(manager, "_ethernet_status", return_value=(True, "10.0.0.8")):
            manager._refresh()
        self.assertEqual(manager.status().mode, "ETHERNET")
        self.assertEqual(manager.status().ip, "10.0.0.8")
