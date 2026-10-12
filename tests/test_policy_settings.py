import json
import re
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import policy  # noqa: E402


@pytest.fixture
def alias_policy(tmp_path, monkeypatch):
    session = tmp_path / "whatsapp" / "session"
    session.mkdir(parents=True)
    phone, lid = "19990000001@s.whatsapp.net", "999000000001@lid"
    (session / "lid-mapping-19990000001.json").write_text('"999000000001"')
    (session / "lid-mapping-999000000001_reverse.json").write_text('"19990000001"')
    monkeypatch.setattr(policy, "POLICY_PATH", tmp_path / "memu.json")
    monkeypatch.setattr(policy, "SESSION_DIR", session)
    monkeypatch.setattr(policy, "CREDS_PATH", session / "creds.json")
    monkeypatch.setattr(policy, "DIRECTORY_PATH", tmp_path / "channel_directory.json")
    monkeypatch.setattr(policy, "GROUP_NAME_CACHE_PATH", tmp_path / "group_names.json")
    return phone, lid


@pytest.mark.parametrize("requested", [0, 1])
@pytest.mark.parametrize("mode,mem", [("full", False), ("listen_only", False), ("excluded", True), ("full", True)])
def test_save_updates_every_existing_alias_without_changing_metadata(alias_policy, requested, mode, mem):
    phone, lid = alias_policy
    unrelated = {"policy": "listen_only", "memorize": False, "display_name": "Fictional Group"}
    rows = {
        phone: {"policy": "listen_only", "memorize": True, "display_name": "TestContact", "phone_jid": phone},
        lid: {"policy": "full", "memorize": False, "lid_jid": lid, "extra": {"keep": True}},
        "120363000000001@g.us": unrelated,
    }
    policy.POLICY_PATH.write_text(json.dumps({"other": "keep", "whatsapp": {"default_policy": "excluded", "channels": rows}}))
    policy.write_channel_settings({alias_policy[requested]: {"policy": mode, "memorize": mem}})
    saved = json.loads(policy.POLICY_PATH.read_text())
    assert saved["other"] == "keep"
    assert saved["whatsapp"]["default_policy"] == "excluded"
    assert set(saved["whatsapp"]["channels"]) == set(rows)
    for key in alias_policy:
        assert saved["whatsapp"]["channels"][key] == {**rows[key], "policy": mode, "memorize": mem and mode != "excluded"}
    assert saved["whatsapp"]["channels"]["120363000000001@g.us"] == unrelated


@pytest.mark.parametrize("missing", [None, "not a boolean"])
@pytest.mark.parametrize("requested", [0, 1])
def test_display_defaults_mem_only_after_combining_explicit_alias_values(alias_policy, missing, requested):
    phone, lid = alias_policy
    second = {"policy": "full", "display_name": "TestContact"}
    if missing is not None:
        second["memorize"] = missing
    policy.POLICY_PATH.write_text(json.dumps({"whatsapp": {"channels": {
        phone: {"policy": "full", "memorize": False}, lid: second,
    }}}))
    settings = policy.read_channel_settings()
    before = json.dumps(settings)
    saved = policy.settings_for_chat(alias_policy[requested], settings)
    assert (saved["policy"], saved["memorize"]) == ("full", False)
    assert json.dumps(settings) == before
    assert settings[lid].get("memorize") == missing


@pytest.mark.parametrize("rows,expected", [
    (({"policy": "full"}, {"policy": "listen_only"}), ("listen_only", True)),
    (({"policy": "listen_only", "memorize": False}, {"policy": "full", "memorize": True}), ("listen_only", True)),
    (({"policy": "excluded", "memorize": False}, {"policy": "full", "memorize": True}), ("excluded", False)),
])
def test_display_matches_consumer_alias_precedence(alias_policy, rows, expected):
    policy.POLICY_PATH.write_text(json.dumps({"whatsapp": {"channels": dict(zip(alias_policy, rows))}}))
    settings = policy.read_channel_settings()
    for key in alias_policy:
        saved = policy.settings_for_chat(key, settings)
        assert (saved["policy"], saved["memorize"]) == expected


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("placeholder", ["19990000001", "19990000001@s.whatsapp.net", "19990000001:4@c.us", "999000000001@lid"])
def test_directory_shows_one_named_control_per_linked_dm(alias_policy, reverse, placeholder):
    phone, lid = alias_policy
    rows = [
        {"id": phone, "name": placeholder, "type": "dm"},
        {"id": lid, "name": "TestContact", "type": "dm"},
    ]
    if reverse:
        rows.reverse()
    group = {"id": "120363000000001@g.us", "name": "Fictional Group", "type": "group"}
    policy.DIRECTORY_PATH.write_text(json.dumps({"platforms": {"whatsapp": [*rows, group]}}))
    assert policy.list_whatsapp_chats() == [group, {"id": lid, "name": "TestContact", "type": "dm"}]


def test_legacy_default_removal_applies_to_each_alias(alias_policy):
    phone, lid = alias_policy
    policy.POLICY_PATH.write_text(json.dumps({"whatsapp": {"channels": {
        phone: {"policy": "listen_only", "memorize": False},
        lid: {"policy": "listen_only", "memorize": False, "display_name": "TestContact"},
    }}}))
    policy.write_channel_settings({phone: {"policy": "full", "memorize": True}})
    assert json.loads(policy.POLICY_PATH.read_text())["whatsapp"]["channels"] == {
        lid: {"policy": "full", "memorize": True, "display_name": "TestContact"},
    }


def test_hermes_form_unchecked_mem_updates_both_aliases(alias_policy, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app

    phone, lid = alias_policy
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(app.soul, "CHANNELS_CONFIG_PATH", config)
    monkeypatch.setattr(app.soul, "read_active_soul_id", lambda: "TestSoul")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["TestSoul"])
    policy.DIRECTORY_PATH.write_text(json.dumps({"platforms": {"whatsapp": [
        {"id": phone, "name": "19990000001", "type": "dm"},
        {"id": lid, "name": "TestContact", "type": "dm"},
    ]}}))
    policy.POLICY_PATH.write_text(json.dumps({"whatsapp": {"default_policy": "excluded", "channels": {
        phone: {"policy": "full", "memorize": True}, lid: {"policy": "full", "memorize": False},
    }}}))
    client = TestClient(app.app, base_url="http://127.0.0.1")
    html = client.get("/hermes").text
    assert html.count('name="policy[') == 1
    pattern = rf'<input[^>]*name="memorize\[{re.escape(lid)}\]"[^>]*>'
    assert "checked" in re.search(pattern, html).group()
    response = client.post("/policy", data={"default_policy": "excluded", f"policy[{lid}]": "full"}, follow_redirects=False)
    assert response.status_code == 303
    assert all(row["memorize"] is False for row in policy.read_channel_settings().values())
    assert "checked" not in re.search(pattern, client.get("/hermes").text).group()


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_alias_save_keeps_whole_file_unchanged(alias_policy, reverse):
    phone, lid = alias_policy
    original = json.dumps({"whatsapp": {"default_policy": "excluded", "channels": {
        phone: {"policy": "full", "memorize": False, "display_name": "TestContact"},
        lid: {"policy": "full", "memorize": False, "lid_jid": lid},
    }}})
    policy.POLICY_PATH.write_text(original)
    items = [(phone, {"policy": "full", "memorize": True}), (lid, {"policy": "full", "memorize": False})]
    if reverse:
        items.reverse()
    with pytest.raises(ValueError, match="same WhatsApp chat"):
        policy.write_channel_settings(dict(items), default_policy="listen_only")
    assert policy.POLICY_PATH.read_text() == original


def test_identical_normalized_alias_choices_can_be_saved(alias_policy):
    phone, lid = alias_policy
    policy.POLICY_PATH.write_text('{"whatsapp":{"channels":{}}}')
    policy.write_channel_settings({
        phone: {"policy": "excluded", "memorize": True},
        lid: {"policy": "excluded", "memorize": False},
    }, default_policy="listen_only")
    saved = json.loads(policy.POLICY_PATH.read_text())["whatsapp"]
    assert saved["default_policy"] == "listen_only"
    assert set(saved["channels"]) == {phone}
    assert policy.settings_for_chat(lid, policy.read_channel_settings())["memorize"] is False


def test_conflicting_open_form_returns_400_without_partial_default_save(alias_policy):
    from fastapi.testclient import TestClient
    import app

    policy.POLICY_PATH.write_text('{"whatsapp":{"default_policy":"excluded","channels":{}}}')
    original = policy.POLICY_PATH.read_text()
    phone, lid = alias_policy
    response = TestClient(app.app, base_url="http://127.0.0.1").post("/policy", data={
        "default_policy": "listen_only", f"policy[{phone}]": "full", f"memorize[{phone}]": "on", f"policy[{lid}]": "full",
    }, follow_redirects=False)
    assert response.status_code == 400
    assert "same WhatsApp chat" in response.json()["detail"]
    assert policy.POLICY_PATH.read_text() == original


@pytest.mark.parametrize("mode,memorize", [("excluded", False), ("full", True)])
def test_read_write_channel_settings_round_trip_preserves_metadata(tmp_path, monkeypatch, mode, memorize):
    policy_path = tmp_path / "memu.json"
    policy_path.write_text(
        json.dumps({
            "whatsapp": {
                "channels": {
                    "test-contact@lid": {
                        "policy": "listen_only",
                        "memorize": False,
                        "display_name": "TestContact",
                        "lid_jid": "test-contact@lid",
                    }
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "POLICY_PATH", policy_path)

    settings = policy.read_channel_settings()
    settings["test-contact@lid"].update(policy=mode, memorize=memorize)
    policy.write_channel_settings(settings)

    data = json.loads(policy_path.read_text(encoding="utf-8"))
    assert data["whatsapp"]["channels"]["test-contact@lid"] == {
        "policy": mode,
        "memorize": memorize,
        "display_name": "TestContact",
        "lid_jid": "test-contact@lid",
    }


def test_write_channel_settings_removes_pure_default_policy_row(tmp_path, monkeypatch):
    policy_path = tmp_path / "memu.json"
    policy_path.write_text(
        json.dumps({
            "whatsapp": {
                "channels": {
                    "test-contact@lid": {"policy": "listen_only", "memorize": False}
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(policy, "POLICY_PATH", policy_path)

    policy.write_channel_settings({
        "test-contact@lid": {"policy": "full", "memorize": True}
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
