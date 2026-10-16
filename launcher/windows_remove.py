"""Remove an installer-owned Apps root after explicit user confirmation."""
from __future__ import annotations

import ctypes
import os
import re
import shutil
from pathlib import Path

import settings
from setup_install import LAUNCHER_UPDATE_DIR, _clear_readonly_and_retry


def _retry_delete(function, path, error) -> None:
    if Path(path).is_symlink() or Path(path).is_junction():
        raise error
    _clear_readonly_and_retry(function, path, error)


def remove_everything(*, confirm: bool = False) -> None:
    preferences = settings.read_paths()
    raw = preferences.get("apps_root")
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

    if confirm and ctypes.windll.user32.MessageBoxW(
        None,
        f"Remove EVERYTHING in this folder?\n\n{root}\n\n"
        "This permanently deletes all files in it, including installed components and soul data, "
        "plus OpenAlma settings and logs. Choose No to preserve them.",
        "OpenAlma - Remove Everything", 0x00000004 | 0x00000010 | 0x00000100,  # Yes/No, error icon, default No.
    ) != 6:
        return
    files = {
        settings.SETTINGS_PATH, settings.LEGACY_SETTINGS_PATH,
        settings.LAUNCHER_LOG_PATH, settings.SETTINGS_ROOT / "logs/launcher.log",
    }
    for path in (settings.SETTINGS_PATH, settings.LEGACY_SETTINGS_PATH):
        files.update(backup for backup in path.parent.glob(f"{path.name}*.orig")
                     if re.fullmatch(rf"{re.escape(path.name)}(?:_(?:[2-9]|[1-9][0-9]+))?\.orig", backup.name)
                     and (backup.is_file() or backup.is_symlink()))
    files.update(path for path in LAUNCHER_UPDATE_DIR.glob("OpenAlma-*-Windows.exe*")
                 if re.fullmatch(r"OpenAlma-v[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9][A-Za-z0-9._-]*)?-Windows\.exe(?:\.part)?", path.name)
                 and (path.is_file() or path.is_symlink()))
    try:
        shutil.rmtree(root, onexc=_retry_delete)
        profile = settings.BROWSER_PROFILE_PATH
        if not profile.is_relative_to(root):
            if profile.is_symlink():
                files.add(profile)
            elif profile.exists():
                shutil.rmtree(profile, onexc=_retry_delete)
        for path in files:
            try:
                path.unlink(missing_ok=True)
            except PermissionError as exc:
                _retry_delete(Path.unlink, path, exc)
    except OSError:
        # Restore only the validated retry controls, never partially deleted data.
        root.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            marker.write_text(owner + "\n", encoding="utf-8")
        if not settings.SETTINGS_PATH.exists():
            settings.write_paths(preferences)
        raise


if __name__ == "__main__":
    remove_everything(confirm=True)
