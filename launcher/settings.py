"""User-overridable path settings for the launcher.

Stored in ``~/.config/memu-stack-launcher/paths.json``. The launcher's
service definitions read ``apps_root()`` here to locate the four
sibling repos (mcp-memu-server, hermes-agent, sillytavern, memu) on
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
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = Path.home() / ".config" / "memu-stack-launcher" / "paths.json"
_AUTODISCOVER_MARKER = "mcp-memu-server/run.py"


def read_paths() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_paths(paths: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(paths, indent=2) + "\n", encoding="utf-8")


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


def apps_root() -> Path | None:
    raw = read_paths().get("apps_root")
    if isinstance(raw, str) and raw.strip():
        candidate = Path(raw.strip()).expanduser()
        if (candidate / _AUTODISCOVER_MARKER).exists():
            return candidate
    return _autodiscover_apps_root()
