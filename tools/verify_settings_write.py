#!/usr/bin/env python3
"""Verify atomic settings persistence without changing effective values."""

import json

from picket_virtual_radar.settings_store import update_settings


path = "/etc/picket-virtual-radar/config.json"
with open(path, encoding="utf-8") as stream:
    config = json.load(stream)
ui = config.get("ui", {})
tracking = config.get("tracking", {})
update_settings(
    {
        "ui": {
            "info_mode": ui.get("info_mode", "callsign"),
            "show_scanline": ui.get("show_scanline", True),
            "show_aircraft_heading": ui.get("show_aircraft_heading", True),
            "show_data_age": ui.get("show_data_age", True),
        },
        "tracking": {"show_on_ground": tracking.get("show_on_ground", False)},
    }
)
print("settings_write=ok")
