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
