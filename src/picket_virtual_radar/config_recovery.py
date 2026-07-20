from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .settings_store import recovery_paths


LOG = logging.getLogger(__name__)
MAX_START_ATTEMPTS = 3


def selected_path() -> Path:
    return Path(os.environ.get("PVR_CONFIG", DEFAULT_CONFIG_PATH))


def prepare_start(path: Path | None = None) -> bool:
    """Count a pending start and restore the backup before attempt four."""
    config_path = path or selected_path()
    backup, pending = recovery_paths(config_path)
    if not pending.exists():
        return False
    try:
        state = json.loads(pending.read_text(encoding="utf-8"))
        attempts = int(state.get("attempts", 0)) + 1
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        attempts = MAX_START_ATTEMPTS
    if attempts >= MAX_START_ATTEMPTS:
        if not backup.exists():
            raise RuntimeError("pending settings failed but no last-known-good backup exists")
        load_config(backup)
        temporary = config_path.with_suffix(config_path.suffix + ".rollback.tmp")
        shutil.copy2(backup, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, config_path)
        pending.unlink(missing_ok=True)
        LOG.error("new settings failed %d starts; restored last-known-good configuration", attempts)
        return True
    temporary = pending.with_suffix(pending.suffix + ".tmp")
    temporary.write_text(json.dumps({"attempts": attempts}) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, pending)
    return False


def confirm_start(path: Path | None = None) -> bool:
    config_path = path or selected_path()
    _backup, pending = recovery_paths(config_path)
    if not pending.exists():
        return False
    pending.unlink()
    LOG.info("new settings confirmed as healthy")
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "confirm"}:
        print("usage: python -m picket_virtual_radar.config_recovery prepare|confirm", file=sys.stderr)
        return 2
    try:
        (prepare_start if sys.argv[1] == "prepare" else confirm_start)()
    except Exception:
        LOG.exception("configuration recovery failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
