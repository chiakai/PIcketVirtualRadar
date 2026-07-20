#!/usr/bin/env python3
"""Verify deployed web authentication without printing secrets or tokens."""

import json
import urllib.error
import urllib.parse
import urllib.request


with open("/etc/picket-virtual-radar/config.json", encoding="utf-8") as stream:
    config = json.load(stream)
token = config["web"]["access_token"]
secret = config.get("opensky", {}).get("client_secret", "")
base = "http://127.0.0.1:8080/"

try:
    urllib.request.urlopen(base, timeout=3)
    anonymous_status = 200
except urllib.error.HTTPError as error:
    anonymous_status = error.code

with urllib.request.urlopen(base + "?" + urllib.parse.urlencode({"token": token}), timeout=3) as response:
    authorized_status = response.status
    page = response.read().decode("utf-8")

print(f"anonymous_status={anonymous_status}")
print(f"authorized_status={authorized_status}")
print(f"settings_form_present={'PIcket Virtual Radar' in page and 'OpenSky OAuth2' in page}")
print(f"client_secret_absent={not secret or secret not in page}")
