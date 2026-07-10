"""Soul selector helpers for the OpenAlma launcher."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import time

from settings import channels_home

_CHANNELS_HOME = channels_home()
HERMES_STATE_DB_PATH = _CHANNELS_HOME / "state.db"
CHANNELS_CONFIG_PATH = _CHANNELS_HOME / "config.json"
DEFAULT_REPLY_PREFIX_TEMPLATE = "✦ *{soul}*: "


def _load_channels_config() -> dict:
    try:
        data = json.loads(CHANNELS_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read {CHANNELS_CONFIG_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected mapping at top level in {CHANNELS_CONFIG_PATH}")
    return data


def _write_channels_config(data: dict) -> None:
    CHANNELS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    dumped = json.dumps(data, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(CHANNELS_CONFIG_PATH.parent),
        delete=False,
    ) as tmp:
        tmp.write(dumped)
        tmp_path = Path(tmp.name)
    tmp_path.replace(CHANNELS_CONFIG_PATH)


def _stamp_soul_active_since(soul_id: str, *, now: float | None = None) -> None:
    selected = str(soul_id or "").strip()
    if not selected:
        raise RuntimeError("Soul ID cannot be empty")
    HERMES_STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(HERMES_STATE_DB_PATH)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS souls ("
            "soul_id TEXT PRIMARY KEY, active_since REAL NOT NULL)"
        )
        con.execute(
            "INSERT OR IGNORE INTO souls (soul_id, active_since) VALUES (?, ?)",
            (selected, float(time.time() if now is None else now)),
        )
        con.commit()
    finally:
        con.close()


def read_active_soul_id() -> str:
    config = _load_channels_config()
    return str(config.get("soul_id") or "").strip()


def read_active_user_id() -> str:
    config = _load_channels_config()
    return str(config.get("user_id") or "").strip()


def list_soul_ids() -> list[str]:
    config = _load_channels_config()
    souls_raw = config.get("souls")
    souls: set[str] = set()
    if isinstance(souls_raw, list):
        for raw in souls_raw:
            sid = str(raw or "").strip()
            if sid:
                souls.add(sid)
    current = str(config.get("soul_id") or "").strip()
    if current:
        souls.add(current)
    return sorted(souls, key=lambda v: v.lower())


def set_active_soul_id(soul_id: str) -> None:
    selected = str(soul_id or "").strip()
    if not selected:
        raise RuntimeError("Soul ID cannot be empty")

    config = _load_channels_config()
    config["soul_id"] = selected

    souls_raw = config.get("souls")
    souls: list[str] = []
    if isinstance(souls_raw, list):
        for raw in souls_raw:
            sid = str(raw or "").strip()
            if sid:
                souls.append(sid)
    if selected not in souls:
        souls.append(selected)
    souls.sort(key=lambda v: v.lower())
    config["souls"] = souls

    template_raw = config.get("reply_prefix_template") or DEFAULT_REPLY_PREFIX_TEMPLATE
    if isinstance(template_raw, str) and "{soul}" in template_raw:
        config["reply_prefix_template"] = template_raw
        config["reply_prefix"] = template_raw.replace("{soul}", selected)

    _write_channels_config(config)
    _stamp_soul_active_since(selected)
