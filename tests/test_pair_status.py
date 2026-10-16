import sys
import subprocess
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


def test_whatsapp_pair_status_trusts_live_web_source_state_over_auth_dir(tmp_path, monkeypatch):
    (tmp_path / "channels_data" / "whatsapp" / "wwebjs_auth").mkdir(parents=True)
    monkeypatch.setattr(services, "_read_channels_config", lambda: {})
    monkeypatch.setattr(services, "_channels_bridge_health", lambda _config=None: {"paired": True, "qr": "bridge-qr"})
    monkeypatch.setattr(services, "_read_channels_web_source_status", lambda: {"state": "pairing", "qr": "web-qr"})
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")

    assert services.whatsapp_pair_status() == {
        "bridge": {"paired": True, "qr": None},
        "websource": {"paired": False, "qr": "web-qr"},
    }


def test_whatsapp_pair_status_uses_auth_dir_when_status_missing(tmp_path, monkeypatch):
    (tmp_path / "channels_data" / "whatsapp" / "wwebjs_auth").mkdir(parents=True)
    monkeypatch.setattr(services, "_read_channels_config", lambda: {})
    monkeypatch.setattr(services, "_channels_bridge_health", lambda _config=None: {})
    monkeypatch.setattr(services, "_read_channels_web_source_status", lambda: {})
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")

    assert services.whatsapp_pair_status() == {
        "bridge": {"paired": False, "qr": None},
        "websource": {"paired": True, "qr": None},
    }


def test_settings_template_contains_inline_whatsapp_pairing():
    text = (Path(__file__).resolve().parents[1] / "launcher" / "templates" / "hermes.html").read_text(encoding="utf-8")

    assert 'id="pair-whatsapp"' in text
    assert 'id="pair-panel"' in text
    assert 'id="websource-qr"' in text
    assert 'id="bridge-qr"' in text
    assert "/static/vendor/qrcode.min.js" in text
    assert "Could not render QR." in text


def test_pair_button_starts_channels_before_polling():
    template = (Path(__file__).resolve().parents[1] / "launcher" / "templates" / "hermes.html").read_text(encoding="utf-8")
    script = template.split('    const pairButton =', 1)[1].split('{% if soul_error %}', 1)[0]
    script = 'const pairButton =' + script
    subprocess.run(["node", "-e", r'''
const assert = require('node:assert/strict'), vm = require('node:vm');
const script = require('node:fs').readFileSync(0, 'utf8');
(async () => {
  for (const mode of ['waiting', 'paired', 'error']) {
    const nodes = {}, calls = [];
    let click, polling = false;
    const context = {
      document: {getElementById(id) { return nodes[id] ||= {
        hidden: true, addEventListener(_event, callback) {click = callback;},
      }; }},
      URLSearchParams, window: {location: {search: ''}},
      QRCode: {toCanvas() {}},
      clearInterval() {polling = false;}, setInterval() {polling = true; return 1;},
      fetch: async (url, options) => {
        calls.push(url);
        if (url === '/service/channels-daemon/start') {
          assert.equal(options.method, 'POST');
          assert.equal(nodes['pair-whatsapp'].disabled, true);
          return {ok: mode !== 'error', json: async () => ({detail: 'Choose a Soul in Setup'})};
        }
        assert.equal(url, '/whatsapp/pair-status');
        const entry = {paired: mode === 'paired', qr: null};
        return {json: async () => ({bridge: entry, websource: entry})};
      },
    };
    vm.runInNewContext(script, context);
    assert.deepEqual(calls, [], 'Opening Setup must not start Hermes');
    await click();
    assert.equal(nodes['pair-whatsapp'].disabled, false);
    if (mode === 'error') {
      assert.deepEqual(calls, ['/service/channels-daemon/start']);
      assert.equal(nodes['pair-status'].textContent, 'Choose a Soul in Setup');
      assert.equal(polling, false);
    } else {
      assert.deepEqual(calls, ['/service/channels-daemon/start', '/whatsapp/pair-status']);
      assert.equal(polling, mode === 'waiting');
      if (mode === 'waiting') assert.equal(nodes['pair-status'].textContent, 'Waiting for WhatsApp QR codes...');
      else assert.equal(nodes['pair-panel'].hidden, true);
    }
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
'''], input=script, text=True, check=True, timeout=15)
