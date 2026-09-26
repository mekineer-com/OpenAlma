"""Browser detection for chromeless app windows."""
from __future__ import annotations

import os
from pathlib import Path
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

_WINDOWS_CHROMIUM_PATHS = (
    ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
    ("LOCALAPPDATA", "Microsoft/Edge/Application/msedge.exe"),
    ("LOCALAPPDATA", "BraveSoftware/Brave-Browser/Application/brave.exe"),
    ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
    ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
    ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
)

_DEFAULT_DEVICE_SCALE_FACTOR = 0.85
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
    if os.name == "nt":
        return _find_windows_chromium()
    return None


def _find_windows_chromium() -> str | None:
    for env_name, relative_path in _WINDOWS_CHROMIUM_PATHS:
        root = os.environ.get(env_name)
        candidate = Path(root, relative_path) if root else None
        if candidate is not None and candidate.is_file():
            return str(candidate)
    return None


def open_app(
    url: str,
    chromium: str | None = None,
    user_data_dir: str | Path | None = None,
    *,
    width: int = 600,
    height: int = 740,
) -> subprocess.Popen | None:
    """Open the launcher UI in a chromeless app window sized to the column.

    Returns the chromium ``Popen`` object so the caller can watch it
    and quit the launcher when the window is closed. Returns ``None``
    for the default-browser fallback (no separate process to watch).
    """
    if chromium:
        if user_data_dir is None:
            raise ValueError("Chromium requires an isolated user-data directory")
        return subprocess.Popen(
            [
                chromium,
                f"--app={url}",
                f"--user-data-dir={user_data_dir}",
                f"--window-size={int(width)},{int(height)}",
                f"--force-device-scale-factor={_DEFAULT_DEVICE_SCALE_FACTOR}",
                "--no-default-browser-check",
                *_CHROMIUM_LOW_OVERHEAD_FLAGS,
            ],
            start_new_session=True,
        )
    webbrowser.open_new(url)
    return None
