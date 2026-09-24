import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import policy  # noqa: E402


def test_write_channel_settings_preserves_metadata_on_default_policy(tmp_path, monkeypatch):
    policy_path = tmp_path / "memu.json"
    policy_path.write_text(
        json.dumps({
            "whatsapp": {
                "channels": {
                    "270699038040215@lid": {
                        "policy": "listen_only",
                        "memorize": False,
                        "display_name": "Annie Gottlieb",
                        "lid_jid": "270699038040215@lid",
                    }
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "POLICY_PATH", policy_path)

    policy.write_channel_settings({
        "270699038040215@lid": {"policy": "full", "memorize": True}
    })

    data = json.loads(policy_path.read_text(encoding="utf-8"))
    assert data["whatsapp"]["channels"]["270699038040215@lid"] == {
        "policy": "full",
        "memorize": True,
        "display_name": "Annie Gottlieb",
        "lid_jid": "270699038040215@lid",
    }


def test_read_write_channel_settings_round_trip_preserves_metadata(tmp_path, monkeypatch):
    policy_path = tmp_path / "memu.json"
    policy_path.write_text(
        json.dumps({
            "whatsapp": {
                "channels": {
                    "270699038040215@lid": {
                        "policy": "listen_only",
                        "memorize": False,
                        "display_name": "Annie Gottlieb",
                        "lid_jid": "270699038040215@lid",
                    }
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "POLICY_PATH", policy_path)

    settings = policy.read_channel_settings()
    settings["270699038040215@lid"]["policy"] = "excluded"
    policy.write_channel_settings(settings)

    data = json.loads(policy_path.read_text(encoding="utf-8"))
    assert data["whatsapp"]["channels"]["270699038040215@lid"] == {
        "policy": "excluded",
        "memorize": False,
        "display_name": "Annie Gottlieb",
        "lid_jid": "270699038040215@lid",
    }


def test_write_channel_settings_removes_pure_default_policy_row(tmp_path, monkeypatch):
    policy_path = tmp_path / "memu.json"
    policy_path.write_text(
        json.dumps({
            "whatsapp": {
                "channels": {
                    "270699038040215@lid": {"policy": "listen_only", "memorize": False}
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "POLICY_PATH", policy_path)

    policy.write_channel_settings({
        "270699038040215@lid": {"policy": "full", "memorize": True}
    })

    data = json.loads(policy_path.read_text(encoding="utf-8"))
    assert data["whatsapp"]["channels"] == {}


def test_existing_chats_are_frozen_full_when_new_default_is_introduced(tmp_path, monkeypatch):
    policy_path = tmp_path / "memu.json"
    policy_path.write_text('{"whatsapp":{"channels":{}}}', encoding="utf-8")
    monkeypatch.setattr(policy, "POLICY_PATH", policy_path)

    settings, default = policy.ensure_channel_settings([
        {"id": "existing@s.whatsapp.net"},
    ])

    assert default == "excluded"
    assert settings["existing@s.whatsapp.net"] == {"policy": "full", "memorize": True}
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    assert data["whatsapp"]["default_policy"] == "excluded"


def test_new_chat_is_frozen_to_selected_default(tmp_path, monkeypatch):
    policy_path = tmp_path / "memu.json"
    policy_path.write_text(
        '{"whatsapp":{"default_policy":"listen_only","channels":{}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "POLICY_PATH", policy_path)

    settings, default = policy.ensure_channel_settings([{"id": "new@g.us"}])
    policy.write_default_policy("full")

    assert default == "listen_only"
    assert settings["new@g.us"] == {"policy": "listen_only", "memorize": True}
    assert policy.read_channel_settings()["new@g.us"]["policy"] == "listen_only"
