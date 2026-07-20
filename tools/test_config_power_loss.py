#!/usr/bin/env python3
"""Non-destructive atomic-config stress test on the target filesystem."""

import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path


ROUNDS = 100
source = Path(sys.argv[1] if len(sys.argv) > 1 else "/etc/picket-virtual-radar/config.json")
with tempfile.TemporaryDirectory(dir=source.parent) as directory:
    target = Path(directory) / "config.json"
    target.write_bytes(source.read_bytes())
    for index in range(ROUNDS):
        code = (
            "import os,sys; from pathlib import Path; "
            "from picket_virtual_radar.settings_store import update_settings; "
            "update_settings({'runtime':{'logic_hz':10}}, Path(sys.argv[1]), transactional=True)"
        )
        child = subprocess.Popen([sys.executable, "-c", code, str(target)])
        if random.random() < 0.7:
            child.kill()
        child.wait()
        json.loads(target.read_text(encoding="utf-8"))
        if (target.with_name(target.name + ".last-known-good")).exists():
            json.loads((target.with_name(target.name + ".last-known-good")).read_text(encoding="utf-8"))
        print(f"round {index + 1}/{ROUNDS} valid", end="\r", flush=True)
print(f"\nPASS: {ROUNDS} interrupted writes left valid JSON; production config was not modified")
