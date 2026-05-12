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


def find_chromium() -> str | None:
    for name in CHROMIUM_FAMILY:
        if shutil.which(name):
            return name
    return None


def open_app(url: str, *, width: int = 760, height: int = 900) -> None:
    """Open the launcher UI in a chromeless app window sized to the column.

    Width defaults to 760px so that with the body's 720px max-width +
    auto margins, the gap between window edge and column is ~20px on
    each side. Caller may override for unusual displays.
    """
    chromium = find_chromium()
    if chromium:
        subprocess.Popen(
            [
                chromium,
                f"--app={url}",
                "--new-window",
                f"--window-size={int(width)},{int(height)}",
            ],
            start_new_session=True,
        )
        return
    webbrowser.open(url)
