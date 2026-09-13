import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import app  # noqa: E402
import services  # noqa: E402


def test_malformed_channels_config_keeps_home_available(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{broken", encoding="utf-8")
    other = services.ServiceSpec(
        "atomic",
        "Atomic Mind Map",
        [],
        tmp_path,
        tmp_path / "atomic.log",
        tmp_path / "atomic.pid",
    )
    monkeypatch.setattr(app.soul, "CHANNELS_CONFIG_PATH", config)
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [other])
    monkeypatch.setattr(app.services, "is_installed", lambda _spec: True)
    monkeypatch.setattr(app.services, "status", lambda _spec: {"state": "stopped"})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    response = TestClient(app.app).get("/")

    assert response.status_code == 200
    assert "Atomic Mind Map" in response.text
    assert "Channels configuration needs repair" in response.text
    assert config.read_text(encoding="utf-8") == "{broken"


def test_fresh_root_shows_core_install_without_runtime_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app.settings, "apps_root", lambda: None)
    monkeypatch.setattr(app.settings, "setup_apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "status", lambda _spec: pytest.fail("runtime status must not run"))
    monkeypatch.setattr(app.setup_install, "setup_status", lambda _root: {
        "state": "setup", "status_label": "Not installed", "detail": "Missing core",
        "startable": False, "action_kind": "install", "action_label": "Install",
    })

    response = TestClient(app.app).get("/")

    assert response.status_code == 200
    assert "memU Server" in response.text
    assert 'action="/install/memu-server"' in response.text
    assert "Hermes Channels" in response.text
    assert "disabled" in response.text


def test_launcher_quit_uses_server_callback(monkeypatch):
    called = []
    monkeypatch.setattr(app.app.state, "request_shutdown", lambda: called.append(True), raising=False)

    response = TestClient(app.app).post("/launcher/quit")

    assert response.json() == {"ok": True}
    assert called == [True]


def test_active_core_enables_optional_install_actions(tmp_path, monkeypatch):
    specs = services.services_for_root(tmp_path)
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: specs)
    monkeypatch.setattr(app.setup_install, "core_issue", lambda _root: "")
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda name, _root: {
        "ready": False, "state": "setup", "status_label": "Not installed",
        "detail": "Missing checkout", "startable": False,
        "action_kind": "install", "action_label": "Install",
    })
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    response = TestClient(app.app).get("/")

    assert response.status_code == 200
    for name in ("iris-server", "atomic", "channels-daemon", "sillytavern"):
        assert f'action="/install/{name}"' in response.text
