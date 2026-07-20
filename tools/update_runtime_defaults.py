#!/usr/bin/env python3
"""Update deployed radar/tracking defaults without exposing other settings."""

import json
import os
from pathlib import Path


path = Path("/etc/picket-virtual-radar/config.json")
metadata = path.stat()
data = json.loads(path.read_text(encoding="utf-8"))
data.setdefault("radar", {}).update(
    {"latitude": 25.080278, "longitude": 121.232222}
)
data.setdefault("tracking", {})["show_on_ground"] = False
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(temporary, metadata.st_mode & 0o777)
os.chown(temporary, metadata.st_uid, metadata.st_gid)
os.replace(temporary, path)
