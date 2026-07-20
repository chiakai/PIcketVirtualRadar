#!/usr/bin/env python3
"""Print only non-sensitive deployed settings."""

import json


with open("/etc/picket-virtual-radar/config.json", encoding="utf-8") as stream:
    config = json.load(stream)

radar = config.get("radar", {})
tracking = config.get("tracking", {})
print(f"latitude={radar.get('latitude')}")
print(f"longitude={radar.get('longitude')}")
print(f"show_on_ground={tracking.get('show_on_ground')}")
