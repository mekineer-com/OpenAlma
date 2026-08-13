import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import soul  # noqa: E402


def _write_cfg(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_stamp_soul_active_since_insert_or_ignore(tmp_path, monkeypatch):
    state_db = tmp_path / "state.db"
    monkeypatch.setattr(soul, "HERMES_STATE_DB_PATH", state_db)

    soul._stamp_soul_active_since("Siri", now=100.0)
    soul._stamp_soul_active_since("Siri", now=200.0)

    con = sqlite3.connect(state_db)
    try:
        rows = con.execute(
            "SELECT soul_id, active_since FROM souls ORDER BY soul_id"
        ).fetchall()
    finally:
        con.close()

    assert rows == [("Siri", 100.0)]


def test_read_active_soul_id(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_cfg(cfg, {"soul_id": "Echo", "user_id": "Marcos"})
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)

    assert soul.read_active_soul_id() == "Echo"


def test_read_active_user_id(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_cfg(cfg, {"soul_id": "Echo", "user_id": "Marcos"})
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)

    assert soul.read_active_user_id() == "Marcos"


def test_list_soul_ids_includes_active(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_cfg(cfg, {"soul_id": "NewSoul", "souls": ["Siri"]})
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)

    ids = soul.list_soul_ids()
    assert "NewSoul" in ids
    assert "Siri" in ids


def test_set_active_soul_id_updates_soul_id_and_souls(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    state_db = tmp_path / "state.db"
    _write_cfg(cfg, {"soul_id": "Siri", "souls": ["Siri"], "user_id": "Marcos"})
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)
    monkeypatch.setattr(soul, "HERMES_STATE_DB_PATH", state_db)

    soul.set_active_soul_id("Echo")

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["soul_id"] == "Echo"
    assert "Echo" in data["souls"]
    assert data["user_id"] == "Marcos"  # unrelated keys preserved


def test_set_active_soul_id_recomputes_reply_prefix_from_template(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    state_db = tmp_path / "state.db"
    _write_cfg(cfg, {
        "soul_id": "Siri",
        "souls": ["Siri"],
        "reply_prefix": "✦ *Siri*: ",
        "reply_prefix_template": "✦ *{soul}*: ",
    })
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)
    monkeypatch.setattr(soul, "HERMES_STATE_DB_PATH", state_db)

    soul.set_active_soul_id("Echo")

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["reply_prefix"] == "✦ *Echo*: "
    assert data["soul_id"] == "Echo"


def test_set_active_soul_id_seeds_reply_prefix_template_when_missing(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    state_db = tmp_path / "state.db"
    _write_cfg(cfg, {
        "soul_id": "Siri",
        "souls": ["Siri"],
        "reply_prefix": "✦ *Siri*: ",
    })
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)
    monkeypatch.setattr(soul, "HERMES_STATE_DB_PATH", state_db)

    soul.set_active_soul_id("Echo")

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["reply_prefix_template"] == "✦ *{soul}*: "
    assert data["reply_prefix"] == "✦ *Echo*: "


def test_set_active_soul_id_preserves_empty_reply_prefix(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_cfg(cfg, {"soul_id": "Siri", "reply_prefix": "old", "reply_prefix_template": ""})
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)
    monkeypatch.setattr(soul, "HERMES_STATE_DB_PATH", tmp_path / "state.db")

    soul.set_active_soul_id("Echo")

    assert json.loads(cfg.read_text(encoding="utf-8"))["reply_prefix"] == ""


def test_set_active_soul_id_rejects_malformed_reply_prefix_template(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_cfg(cfg, {"soul_id": "Siri", "reply_prefix_template": "no placeholder"})
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)

    with pytest.raises(RuntimeError, match=r"contain \{soul\}"):
        soul.set_active_soul_id("Echo")


def test_set_active_soul_id_does_not_stamp_when_write_fails(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_cfg(cfg, {"soul_id": "Siri", "souls": ["Siri"]})
    monkeypatch.setattr(soul, "CHANNELS_CONFIG_PATH", cfg)
    monkeypatch.setattr(soul, "_write_channels_config", lambda _d: (_ for _ in ()).throw(RuntimeError("write failed")))
    stamped = []
    monkeypatch.setattr(soul, "_stamp_soul_active_since", lambda *_a, **_k: stamped.append(True))

    with pytest.raises(RuntimeError, match="write failed"):
        soul.set_active_soul_id("Echo")

    assert stamped == []
