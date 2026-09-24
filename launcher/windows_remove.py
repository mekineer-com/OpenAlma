"""Remove an installer-owned Apps root after explicit user confirmation."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import settings
from setup_install import _clear_readonly_and_retry


def remove_everything() -> None:
    raw = settings.read_paths().get("apps_root")
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("Recorded OpenAlma Apps root is unavailable")
    root = Path(raw).expanduser().resolve()
    marker = root / ".openalma-root"
    try:
        owner = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("OpenAlma Apps-root ownership marker is unavailable") from exc
    if os.path.normcase(owner) != os.path.normcase(str(root)):
        raise RuntimeError("OpenAlma Apps-root ownership marker does not match")

    shutil.rmtree(root, onexc=_clear_readonly_and_retry)
    shutil.rmtree(settings.SETTINGS_PATH.parent, ignore_errors=True)
    if not settings.LAUNCHER_LOG_PATH.is_relative_to(root):
        settings.LAUNCHER_LOG_PATH.unlink(missing_ok=True)
        for directory in (settings.LAUNCHER_LOG_PATH.parent, settings.LAUNCHER_LOG_PATH.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                break


if __name__ == "__main__":
    remove_everything()
