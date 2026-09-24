"""User-overridable path settings for the launcher.

Stored in ``~/.config/openalma-launcher/paths.json``. The launcher captures
``apps_root()`` once at startup to locate the four
sibling repos (mcp-memu-server, hermes-channels, sillytavern, memu) on
disk. Resolution order:

1. Explicit ``apps_root`` field in the JSON file (user setting).
2. Auto-discovery walking up from the launcher's own directory until
   a parent contains ``mcp-memu-server/run.py``. This works when the
   four repos are cloned side-by-side under one parent.
3. Returns ``None`` — the launcher's index page surfaces a "Setup
   needed" banner pointing the user at ``/settings``.

There is no hardcoded personal-machine fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parent
PACKAGED_VERSION_PATH = LAUNCHER_DIR.parent / ".openalma-version"
PACKAGED_MANIFEST_PATH = LAUNCHER_DIR.parent / "release-components.json"
SETTINGS_PATH = Path.home() / ".config" / "openalma-launcher" / "paths.json"
LAUNCHER_LOG_PATH = (
    Path(os.environ["LOCALAPPDATA"]) / "OpenAlma" / "logs" / "launcher.log"
    if os.name == "nt" and os.environ.get("LOCALAPPDATA")
    else Path.home() / ".local" / "state" / "openalma" / "launcher.log"
)
_AUTODISCOVER_MARKER = "mcp-memu-server/run.py"


def read_paths() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_paths(paths: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(paths, indent=2) + "\n", encoding="utf-8")
    temporary.replace(SETTINGS_PATH)


def _autodiscover_apps_root() -> Path | None:
    cur = LAUNCHER_DIR
    # Walk up at most 5 levels — apps_root is normally two levels up
    # (launcher → memu-local-stack → apps_root) but allow some slack
    # for unconventional layouts.
    for _ in range(5):
        cur = cur.parent
        if (cur / _AUTODISCOVER_MARKER).exists():
            return cur
    return None


def resolve_apps_root(raw: object) -> Path | None:
    if isinstance(raw, str) and raw.strip():
        candidate = Path(raw.strip()).expanduser()
        if (candidate / _AUTODISCOVER_MARKER).exists():
            return candidate.resolve()
    return None


def next_apps_root(raw: object) -> Path | None:
    return resolve_apps_root(raw) if isinstance(raw, str) and raw.strip() else _autodiscover_apps_root()


def setup_apps_root() -> Path | None:
    """Return an existing directory where core can be prepared."""
    raw = read_paths().get("apps_root")
    if isinstance(raw, str) and raw.strip():
        candidate = Path(raw.strip()).expanduser()
    else:
        candidate = LAUNCHER_DIR.parents[1]
    try:
        return candidate.resolve() if candidate.is_dir() else None
    except OSError:
        return None


_ACTIVE_APPS_ROOT = resolve_apps_root(read_paths().get("apps_root")) or _autodiscover_apps_root()
if _ACTIVE_APPS_ROOT is not None:
    _ACTIVE_APPS_ROOT = _ACTIVE_APPS_ROOT.resolve()


def apps_root() -> Path | None:
    return _ACTIVE_APPS_ROOT


def _active_channels_home() -> Path:
    raw = os.environ.get("CHANNELS_HOME")
    if raw and raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    root = apps_root()
    if root is not None:
        return root / "hermes-channels" / "data"
    return (LAUNCHER_DIR.parents[1] / "hermes-channels" / "data").resolve()


_ACTIVE_CHANNELS_HOME = _active_channels_home()


def channels_home() -> Path:
    return _ACTIVE_CHANNELS_HOME


def atomic_server_binary(root: Path) -> Path:
    filename = "atomic-server.exe" if os.name == "nt" else "atomic-server"
    production = root / "atomic" / "target" / "server" / filename
    debug = root / "atomic" / "target" / "debug" / filename
    return production if production.exists() or not debug.exists() else debug
