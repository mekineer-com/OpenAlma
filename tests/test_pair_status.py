import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import services  # noqa: E402


def test_whatsapp_pair_status_reads_channels_state(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "_read_channels_config", lambda: {"bridge_port": 3000})
    monkeypatch.setattr(services, "_channels_bridge_health", lambda _config=None: {"status": "connecting", "qr": "bridge-qr"})
    monkeypatch.setattr(services, "_read_channels_web_source_status", lambda: {"state": "pairing", "qr": "web-qr"})
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")

    assert services.whatsapp_pair_status() == {
        "bridge": {"paired": False, "qr": "bridge-qr"},
        "websource": {"paired": False, "qr": "web-qr"},
    }


def test_whatsapp_pair_status_hides_qr_when_paired(tmp_path, monkeypatch):
    (tmp_path / "channels_data" / "whatsapp" / "wwebjs_auth").mkdir(parents=True)
    monkeypatch.setattr(services, "_read_channels_config", lambda: {})
    monkeypatch.setattr(services, "_channels_bridge_health", lambda _config=None: {"paired": True, "qr": "bridge-qr"})
    monkeypatch.setattr(services, "_read_channels_web_source_status", lambda: {"state": "pairing", "qr": "web-qr"})
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")

    assert services.whatsapp_pair_status() == {
        "bridge": {"paired": True, "qr": None},
        "websource": {"paired": True, "qr": None},
    }


def test_settings_template_contains_inline_whatsapp_pairing():
    text = (Path(__file__).resolve().parents[1] / "launcher" / "templates" / "settings.html").read_text(encoding="utf-8")

    assert 'id="pair-whatsapp"' in text
    assert "/static/vendor/qrcode.min.js" in text
