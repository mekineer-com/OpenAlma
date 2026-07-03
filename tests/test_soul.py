import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
sys.modules.setdefault("yaml", SimpleNamespace(safe_load=lambda _raw: {}, safe_dump=lambda *_a, **_k: ""))

import soul  # noqa: E402


def test_stamp_soul_active_since_insert_or_ignore(tmp_path, monkeypatch):
    state_db = tmp_path / "state.db"
    monkeypatch.setattr(soul, "HERMES_STATE_DB_PATH", state_db)

    soul._stamp_soul_active_since("Siri", now=100.0)
    soul._stamp_soul_active_since("Siri", now=200.0)

    import sqlite3

    con = sqlite3.connect(state_db)
    try:
        rows = con.execute(
            "SELECT soul_id, active_since FROM souls ORDER BY soul_id"
        ).fetchall()
    finally:
        con.close()

    assert rows == [("Siri", 100.0)]


def test_set_active_soul_id_does_not_stamp_when_config_write_fails(monkeypatch):
    monkeypatch.setattr(
        soul,
        "_load_config",
        lambda: {"soul_mode": {"agents": {"main": {"role": "soul", "soul_id": "Echo"}}}},
    )
    monkeypatch.setattr(soul, "_write_config", lambda _config: (_ for _ in ()).throw(RuntimeError("write failed")))
    stamped = []
    monkeypatch.setattr(soul, "_stamp_soul_active_since", lambda *_a, **_k: stamped.append(True))

    with pytest.raises(RuntimeError, match="write failed"):
        soul.set_active_soul_id("Siri")

    assert stamped == []


def test_read_active_user_id_from_first_soul_agent(monkeypatch):
    monkeypatch.setattr(
        soul,
        "_load_config",
        lambda: {"soul_mode": {"agents": {"main": {"role": "soul", "soul_id": "Siri", "user_id": "Marcos"}}}},
    )

    assert soul.read_active_user_id() == "Marcos"


def test_set_active_soul_id_writes_channels_config(tmp_path, monkeypatch):
    channels_cfg = tmp_path / "config.json"
    channels_cfg.write_text(
        json.dumps({"soul_id": "OldSoul", "user_id": "Marcos"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", channels_cfg)
    monkeypatch.setattr(
        soul,
        "_load_config",
        lambda: {"soul_mode": {"agents": {"main": {"role": "soul", "soul_id": "OldSoul"}}}},
    )
    monkeypatch.setattr(soul, "_write_config", lambda _c: None)
    monkeypatch.setattr(soul, "_stamp_soul_active_since", lambda *_a, **_k: None)

    soul.set_active_soul_id("NewSoul")

    data = json.loads(channels_cfg.read_text(encoding="utf-8"))
    assert data["soul_id"] == "NewSoul"
    assert data["user_id"] == "Marcos"  # unknown keys preserved


def test_set_active_soul_id_writes_reply_prefix_to_channels_config(tmp_path, monkeypatch):
    channels_cfg = tmp_path / "config.json"
    channels_cfg.write_text(json.dumps({"soul_id": "OldSoul"}), encoding="utf-8")
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", channels_cfg)
    monkeypatch.setattr(
        soul,
        "_load_config",
        lambda: {
            "soul_mode": {"agents": {"main": {"role": "soul", "soul_id": "OldSoul"}}},
            "whatsapp": {"reply_prefix": "Echo:", "reply_prefix_template": "{soul}:"},
        },
    )
    monkeypatch.setattr(soul, "_write_config", lambda _c: None)
    monkeypatch.setattr(soul, "_stamp_soul_active_since", lambda *_a, **_k: None)

    soul.set_active_soul_id("NewSoul")

    data = json.loads(channels_cfg.read_text(encoding="utf-8"))
    assert data["soul_id"] == "NewSoul"
    assert data["reply_prefix"] == "NewSoul:"
