"""Browser detection for chromeless app windows."""
from __future__ import annotations

import shutil
import subprocess
import webbrowser

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

_DEFAULT_DEVICE_SCALE_FACTOR = 0.75
_CHROMIUM_LOW_OVERHEAD_FLAGS = [
    "--disable-extensions",
    "--disable-sync",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--no-first-run",
    "--disable-features=MediaRouter",
]


def find_chromium() -> str | None:
    for name in CHROMIUM_FAMILY:
        if shutil.which(name):
            return name
    return None


def open_app(url: str, *, width: int = 600, height: int = 740) -> subprocess.Popen | None:
    """Open the launcher UI in a chromeless app window sized to the column.

    Returns the chromium ``Popen`` object so the caller can watch it
    and quit the launcher when the window is closed. Returns ``None``
    for the default-browser fallback (no separate process to watch).
    """
    chromium = find_chromium()
    if chromium:
        return subprocess.Popen(
            [
                chromium,
                f"--app={url}",
                f"--window-size={int(width)},{int(height)}",
                f"--force-device-scale-factor={_DEFAULT_DEVICE_SCALE_FACTOR}",
                "--no-default-browser-check",
                *_CHROMIUM_LOW_OVERHEAD_FLAGS,
            ],
            start_new_session=True,
        )
    webbrowser.open(url)
    return None
