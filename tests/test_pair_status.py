import sys
import subprocess
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("auth_dir", [False, True])
@pytest.mark.parametrize("web_enabled", [None, False])
@pytest.mark.parametrize("bridge_paired", [False, True])
def test_whatsapp_pair_status_missing_web_status_is_not_pairing_evidence(
    tmp_path, monkeypatch, auth_dir, web_enabled, bridge_paired,
):
    if auth_dir:
        (tmp_path / "channels_data" / "whatsapp" / "wwebjs_auth").mkdir(parents=True)
    config = {} if web_enabled is None else {"web_source_enabled": web_enabled}
    monkeypatch.setattr(services, "_read_channels_config", lambda: config)
    monkeypatch.setattr(services, "_channels_bridge_health", lambda _config=None: {"paired": bridge_paired})
    monkeypatch.setattr(services, "_read_channels_web_source_status", lambda: {})
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")

    assert services.whatsapp_pair_status() == {
        "bridge": {"paired": bridge_paired, "qr": None},
        "websource": {"paired": web_enabled is False, "qr": None},
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
  for (const mode of ['waiting', 'progression', 'paired', 'error']) {
    const nodes = {}, calls = [];
    const rendered = [];
    let click, poll, phase = 0, polling = false;
    const context = {
      document: {getElementById(id) { return nodes[id] ||= {
        hidden: true, addEventListener(_event, callback) {click = callback;},
      }; }},
      URLSearchParams, window: {location: {search: ''}},
      QRCode: {toCanvas(_canvas, qr) {rendered.push(qr);}},
      clearInterval() {polling = false;}, setInterval(callback) {poll = callback; polling = true; return 1;},
      fetch: async (url, options) => {
        calls.push(url);
        if (url === '/service/channels-daemon/start') {
          assert.equal(options.method, 'POST');
          assert.equal(nodes['pair-whatsapp'].disabled, true);
          return {ok: mode !== 'error', json: async () => ({detail: 'Choose a Soul in Setup'})};
        }
        assert.equal(url, '/whatsapp/pair-status');
        const entry = {paired: mode === 'paired' || phase === 2, qr: phase === 1 ? 'web-qr' : null};
        return {json: async () => ({bridge: mode === 'progression' ? {paired: true, qr: null} : entry, websource: entry})};
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
      assert.equal(polling, mode !== 'paired');
      if (mode !== 'paired') assert.equal(nodes['pair-status'].textContent, 'Waiting for WhatsApp QR codes...');
      else assert.equal(nodes['pair-panel'].hidden, true);
      if (mode === 'progression') {
        assert.equal(nodes['pair-panel'].hidden, false);
        phase = 1;
        await poll();
        assert.equal(polling, true);
        assert.equal(nodes['pair-panel'].hidden, false);
        assert.equal(nodes['websource-qr'].hidden, false);
        assert.deepEqual(rendered, ['web-qr']);
        phase = 2;
        await poll();
        assert.equal(nodes['pair-panel'].hidden, true);
        assert.equal(polling, false);
      }
    }
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
'''], input=script, text=True, check=True, timeout=15)
