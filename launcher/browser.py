"""Browser detection for chromeless app windows."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import webbrowser
from pathlib import Path

# Priority order: Chromium-family browsers support `--app=URL` (chromeless window).
# Firefox dropped SSB years ago and cannot deliver a solitary window.
CHROMIUM_FAMILY = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
    "brave-browser",
    "brave",
    "vivaldi",
    "vivaldi-stable",
]

# Dedicated profile dir for the launcher's app window. Without this,
# Chrome routes the --app invocation through the user's already-running
# Chrome instance — which ignores --window-size on the new window.
_PROFILE_DIR = Path.home() / ".cache" / "memu-stack-launcher" / "chrome-profile"
_PROFILE_PREFS = _PROFILE_DIR / "Default" / "Preferences"
_ZOOM_HOSTS = ("127.0.0.1", "localhost")
_DEFAULT_ZOOM_PERCENT = 75.0


def find_chromium() -> str | None:
    for name in CHROMIUM_FAMILY:
        if shutil.which(name):
            return name
    return None


def _scan_host_zoom_levels(node: object) -> float | None:
    if not isinstance(node, dict):
        return None
    for host in _ZOOM_HOSTS:
        host_data = node.get(host)
        if isinstance(host_data, dict):
            zoom_level = host_data.get("zoom_level")
            if isinstance(zoom_level, (int, float)):
                return float(zoom_level)
        elif isinstance(host_data, (int, float)):
            return float(host_data)
    for value in node.values():
        zoom_level = _scan_host_zoom_levels(value)
        if zoom_level is not None:
            return zoom_level
    return None


def _zoom_percent_to_level(percent: float) -> float:
    # Chromium stores zoom level where scale = 1.2 ** level.
    return math.log(percent / 100.0, 1.2)


def _ensure_default_zoom_level() -> None:
    if not _PROFILE_PREFS.exists():
        return
    try:
        payload = json.loads(_PROFILE_PREFS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    partition = payload.get("partition")
    if not isinstance(partition, dict):
        return

    existing_default = partition.get("default_zoom_level")
    if isinstance(existing_default, (int, float)):
        return

    per_host = partition.get("per_host_zoom_levels")
    host_zoom = _scan_host_zoom_levels(per_host)
    if host_zoom is None:
        host_zoom = _zoom_percent_to_level(_DEFAULT_ZOOM_PERCENT)

    partition["default_zoom_level"] = host_zoom
    payload["partition"] = partition
    try:
        _PROFILE_PREFS.write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )
    except OSError:
        return


def open_app(url: str, *, width: int = 760, height: int = 900) -> subprocess.Popen | None:
    """Open the launcher UI in a chromeless app window sized to the column.

    Uses a dedicated ``--user-data-dir`` so Chrome treats this as a
    separate instance (not a second window of the user's running
    browser). That is the only way ``--window-size`` actually applies.

    Returns the chromium ``Popen`` object so the caller can watch it
    and quit the launcher when the window is closed. Returns ``None``
    for the default-browser fallback (no separate process to watch).
    """
    chromium = find_chromium()
    if chromium:
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _ensure_default_zoom_level()
        return subprocess.Popen(
            [
                chromium,
                f"--app={url}",
                f"--window-size={int(width)},{int(height)}",
                f"--user-data-dir={_PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            start_new_session=True,
        )
    webbrowser.open(url)
    return None
