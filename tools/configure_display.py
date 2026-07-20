#!/usr/bin/env python3
"""Safely set the installed PiTFT brightness and orientation defaults."""

import json
import os
import sys
from pathlib import Path


path = Path(sys.argv[1] if len(sys.argv) > 1 else "/etc/picket-virtual-radar/config.json")
data = json.loads(path.read_text(encoding="utf-8"))
data.setdefault("display", {})["brightness_percent"] = 80
data.setdefault("touch", {})["rotation"] = 90
temporary = path.with_suffix(path.suffix + ".display.tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
