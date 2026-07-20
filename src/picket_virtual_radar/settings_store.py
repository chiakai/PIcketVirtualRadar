from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_PATH, load_config


def recovery_paths(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(path.name + ".last-known-good"),
        path.with_name(path.name + ".pending"),
    )


def update_settings(
    changes: dict[str, dict[str, Any]],
    path: Path | None = None,
    *,
    transactional: bool = False,
) -> None:
    selected = path or Path(os.environ.get("PVR_CONFIG", DEFAULT_CONFIG_PATH))
    data: dict[str, Any] = {}
    if selected.exists():
        with selected.open("r", encoding="utf-8") as stream:
            loaded = json.load(stream)
        if not isinstance(loaded, dict):
            raise ValueError("configuration root must be an object")
        data = loaded
    for section, values in changes.items():
        current = data.setdefault(section, {})
        if not isinstance(current, dict):
            raise ValueError(f"configuration section {section} must be an object")
        current.update(values)

    selected.parent.mkdir(parents=True, exist_ok=True)
    temporary = selected.with_suffix(selected.suffix + ".tmp")
    mode = (selected.stat().st_mode & 0o777) if selected.exists() else 0o600
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    # Validate the complete candidate, including unchanged sections, before it
    # can replace the running configuration.
    load_config(temporary)
    if transactional:
        backup, pending = recovery_paths(selected)
        if selected.exists():
            shutil.copy2(selected, backup)
            os.chmod(backup, 0o600)
        pending_temporary = pending.with_suffix(pending.suffix + ".tmp")
        pending_temporary.write_text('{"attempts": 0}\n', encoding="utf-8")
        os.chmod(pending_temporary, 0o600)
        os.replace(pending_temporary, pending)
    os.replace(temporary, selected)
