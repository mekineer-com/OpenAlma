"""Browser detection for chromeless app windows."""
from __future__ import annotations

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


def find_chromium() -> str | None:
    for name in CHROMIUM_FAMILY:
        if shutil.which(name):
            return name
    return None


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
