import json
import subprocess
import sys
import urllib.error
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import app
import services


def test_mentra_apk_resolves_real_uploaded_fork_asset(monkeypatch):
    def asset(build):
        name = f"OpenAlma-Mentra-3.2.1-{build}.apk"
        return {"name": name, "state": "uploaded", "size": 100,
                "browser_download_url": f"https://github.com/mekineer-com/MentraOS/releases/download/v3.2.1/{name}"}

    release = {"tag_name": "v3.2.1", "draft": False, "prerelease": False,
               "assets": [asset(302010001), asset(302010002)]}
    monkeypatch.setattr(services.urllib.request, "urlopen", lambda *_args, **_kwargs: BytesIO(json.dumps(release).encode()))
    url, error = services.mentra_apk_download()
    assert url == asset(302010002)["browser_download_url"]
    assert not error
    for change in ({"prerelease": True}, {"assets": []}, {"tag_name": "v3.2.1-beta"},
                   {"assets": [{**asset(302010002), "browser_download_url": "https://other.invalid/app.apk"}]},
                   {"assets": [{**asset(302010002), "state": "new"}]},
                   {"assets": [{**asset(302010002), "size": 0}]}):
        original = release.copy()
        release.update(change)
        assert services.mentra_apk_download()[0] is None
        release.clear()
        release.update(original)


def test_mentra_qr_url_uses_releases_page_when_release_missing(monkeypatch):
    def missing(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://api.github.com", 404, "Not Found", {}, None)

    monkeypatch.setattr(services.urllib.request, "urlopen", missing)
    client = TestClient(app.app, base_url="http://127.0.0.1")
    assert client.get("/mentra/apk").json() == {"url": "https://github.com/mekineer-com/MentraOS/releases"}
    url = "https://github.com/mekineer-com/MentraOS/releases/download/v3.2.1/OpenAlma-Mentra-3.2.1-302010001.apk"
    monkeypatch.setattr(services, "mentra_apk_download", lambda: (url, ""))
    assert client.get("/mentra/apk").json() == {"url": url}


def test_mentra_download_controls_survive_status_poll_and_pending_actions():
    root = Path(__file__).resolve().parents[1] / "launcher"
    script = r"""
const fs = require('fs'), vm = require('vm');
global.esc = value => String(value || '');
global.actionHtml = (_name, data) => irisParentActions(data);
global.pendingStops = {};
global.pendingStarts = {};
vm.runInThisContext(fs.readFileSync(process.argv[1] + '/static/iris-services.js', 'utf8'));
global.renderIrisInstallations = () => {};
const source = fs.readFileSync(process.argv[1] + '/templates/index.html', 'utf8');
vm.runInThisContext(source.slice(source.indexOf('function pollStatus'), source.indexOf("{% for s in services + not_installed_services if")));
(async () => {
  const results = [];
  for (const pending of ['none', 'stop', 'start', 'error', 'installing']) {
    const status = {}, actions = {};
    const row = {dataset:{runtime:'true'}, querySelector: key => key === '.svc-status' ? status : actions};
    global.document = {querySelector: () => row};
    global.fetch = async () => ({json: async () => ({state:pending === 'error' ? 'unavailable' : pending === 'installing' ? 'installing' : 'ready', status_label:pending === 'error' ? 'Status unavailable' : pending === 'installing' ? 'Installing Iris' : 'Host ready'})});
    pendingStops = pending === 'stop' ? {'iris-server':true} : {};
    pendingStarts = pending === 'start' ? {'iris-server':Date.now()+10000} : {};
    pollStatus('iris-server');
    await new Promise(resolve => setImmediate(resolve));
    results.push([status.innerHTML, actions.innerHTML]);
  }
  const urls = [], canvas = {}, message = {};
  document.getElementById = id => id === 'mentra-apk-qr' ? canvas : message;
  global.QRCode = {toCanvas: async (_canvas, url) => urls.push(url)};
  for (const url of ['https://github.com/mekineer-com/MentraOS/releases', 'https://github.com/mekineer-com/MentraOS/releases/download/v3.2.1/fixture.apk']) {
    global.fetch = async () => ({ok:true,json:async () => ({url})});
    await mentraApkQr();
    if (canvas.hidden || message.textContent) throw new Error('QR not visible');
  }
  results.push(urls);
  console.log(JSON.stringify(results));
})();
"""
    rows = json.loads(subprocess.check_output(["node", "-e", script, str(root)], text=True, encoding="utf-8"))
    for status, actions in rows[:5]:
        assert 'href="https://openalma.org/mentra"' not in status
        assert 'href="https://github.com/mekineer-com/MentraOS/releases"' in status
        assert '>apk on github</a>' in status
        assert 'Host ready' not in status
        assert actions.index('>QR</button>') < actions.index('>Setup</a>')
        assert 'popovertarget="mentra-apk-popup"' in actions
        assert 'href="/iris"' in actions
    assert 'Status unavailable' in rows[3][0]
    assert 'Installing Iris' in rows[4][0]
    assert rows[5] == ['https://github.com/mekineer-com/MentraOS/releases',
                       'https://github.com/mekineer-com/MentraOS/releases/download/v3.2.1/fixture.apk']
